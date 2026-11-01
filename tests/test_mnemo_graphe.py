"""Graphe de connaissances de M10 : schéma fermé, Loi 25, cycle de vie des arêtes, validité temporelle, requêtes
bornées.

Chaque test tourne sur DEUX moteurs derrière le même port : l'adaptateur SQL natif (base SQLite migrée jusqu'à 0052,
déclencheurs append-only compris) et le double en mémoire. Données fictives. Aucun réseau.
"""

from __future__ import annotations

import hashlib
import random

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from opsys.mnemo import codes
from opsys.mnemo.codes import ErreurMnemo
from opsys.mnemo.graphe import DemandeArete, GrapheMemoire, GrapheSql, NoeudRef, schema

FICTIF = True
T0 = "2026-11-01T12:00:00+00:00"
HUMAIN = {"par": "direction.fictive", "mode": "humain", "role": "admin"}
AGENT = {"par": "agent:m10-memoire", "mode": "agent", "role": None}


def pseudo(nom: str) -> str:
    return hashlib.sha256(f"fictif|{nom}".encode()).hexdigest()[:32]


def client(nom: str) -> NoeudRef:
    return NoeudRef("client", pseudo(nom))


def propriete(nom: str) -> NoeudRef:
    return NoeudRef("propriete", pseudo(nom))


def inter(cle: str) -> NoeudRef:
    return NoeudRef("intervention", cle)


def demande(type_arete, de, vers, valide_de="2026-01-01", origine="agent", ref="test:source-fictive", **kw):
    return DemandeArete(
        type=type_arete,
        de=de,
        vers=vers,
        valide_de=valide_de,
        origine=origine,
        source_type="test_fictif",
        source_ref=ref,
        **kw,
    )


@pytest.fixture(params=["sql", "memoire"])
def moteur(request, session):
    if request.param == "memoire":
        yield GrapheMemoire()
        return
    with session() as cnx:
        yield GrapheSql(cnx)


def confirmer(moteur, arete, quand=T0):
    return moteur.confirmer_arete(arete.arete_id, quand=quand, raison="vérifié", **HUMAIN)


# ----------------------------------------------------------------------------------------------- schéma fermé
def test_une_arete_hors_du_schema_est_refusee(moteur):
    with pytest.raises(ErreurMnemo, match=codes.ARETE_NON_AUTORISEE):
        moteur.proposer_arete(demande("inventee", inter("I-1"), NoeudRef("materiau", "m1")), par="a", quand=T0)
    with pytest.raises(
        ErreurMnemo, match=codes.ARETE_NON_AUTORISEE
    ):  # sens inverse : utilise va de l'intervention au matériau
        moteur.proposer_arete(demande("utilise", NoeudRef("materiau", "m1"), inter("I-1")), par="a", quand=T0)
    with pytest.raises(ErreurMnemo, match=codes.ARETE_NON_AUTORISEE):  # types d'extrémités incompatibles
        moteur.proposer_arete(demande("possede", client("a"), NoeudRef("fournisseur", "f1")), par="a", quand=T0)
    with pytest.raises(ErreurMnemo, match=codes.ARETE_NON_AUTORISEE):  # un nœud ne se relie pas à lui-même
        moteur.proposer_arete(demande("precede", inter("I-1"), inter("I-1")), par="a", quand=T0)


def test_un_type_de_noeud_inconnu_est_refuse(moteur):
    with pytest.raises(ErreurMnemo, match=codes.NOEUD_TYPE_INCONNU):
        moteur.poser_noeud("employe", "x", None, source_ref="test:s", par="a", quand=T0)


def test_toute_combinaison_du_schema_est_acceptee_et_aucune_autre():
    for type_arete, couples in schema.ARETES.items():
        for a in schema.TYPES_NOEUD:
            for b in schema.TYPES_NOEUD:
                if (a, b) in couples:
                    schema.verifier_arete(type_arete, a, b)
                else:
                    with pytest.raises(ErreurMnemo):
                        schema.verifier_arete(type_arete, a, b)


# ----------------------------------------------------------------------------------------------- Loi 25
@pytest.mark.parametrize(
    "cle",
    [
        "Jean Tremblay",
        "jean.tremblay@example.test",
        "514-555-0199",
        "123 rue des Érables",
        "H2X 1Y4",
        "ABC",
        "g" * 32,
        "A" * 32,
    ],
)
def test_un_client_ou_une_propriete_n_est_connu_que_par_son_pseudonyme(moteur, cle):
    for type_noeud in ("client", "propriete"):
        with pytest.raises(ErreurMnemo, match=codes.NOEUD_CLE_INVALIDE):
            moteur.poser_noeud(type_noeud, cle, None, source_ref="test:s", par="a", quand=T0)


def test_le_libelle_d_un_noeud_personnel_est_calcule_et_ne_se_fournit_pas(moteur):
    n = moteur.poser_noeud("client", pseudo("c1"), None, source_ref="test:s", par="a", quand=T0)
    assert n.libelle == f"client·{pseudo('c1')[:8]}"
    with pytest.raises(ErreurMnemo, match=codes.DONNEE_PERSONNELLE):
        moteur.poser_noeud("client", pseudo("c2"), "Jean Tremblay", source_ref="test:s", par="a", quand=T0)


@pytest.mark.parametrize(
    "libelle",
    [
        "écrire à jean@example.test",
        "appeler le 514 555 0199",
        "chez Jean Tremblay",
        "123 rue des Érables",
        "https://exemple.test/x",
        "x" * 81,
    ],
)
def test_un_libelle_non_personnel_ne_porte_aucune_donnee_personnelle(moteur, libelle):
    with pytest.raises(ErreurMnemo, match="REJ-MNEMO-(DONNEE-PERSONNELLE|ENTREE-INVALIDE)"):
        moteur.poser_noeud("fournisseur", "f-1", libelle, source_ref="test:s", par="a", quand=T0)


def test_un_noeud_pose_deux_fois_garde_son_premier_libelle(moteur):
    a = moteur.poser_noeud("fournisseur", "f-1", "Fournisseur fictif A", source_ref="test:s", par="a", quand=T0)
    b = moteur.poser_noeud(
        "fournisseur", "f-1", "Autre nom", source_ref="test:s", par="b", quand="2026-11-02T00:00:00+00:00"
    )
    assert a == b and b.libelle == "Fournisseur fictif A"


# ----------------------------------------------------------------------------------------------- cycle de vie
def test_une_arete_sensible_naît_en_brouillon_et_se_confirme_par_une_personne_seulement(moteur):
    p = moteur.proposer_arete(demande("possede", client("c1"), propriete("p1")), par="a", quand=T0)
    assert p.creee and p.arete.etat == "brouillon" and p.arete.sensible
    with pytest.raises(ErreurMnemo, match=codes.HUMAIN_REQUIS):
        moteur.confirmer_arete(p.arete.arete_id, quand=T0, raison=None, **AGENT)
    with pytest.raises(ErreurMnemo, match=codes.HUMAIN_REQUIS):
        moteur.confirmer_arete(p.arete.arete_id, quand=T0, raison=None, par="systeme", mode="systeme", role=None)
    assert moteur.arete(p.arete.arete_id).etat == "brouillon"
    ok = confirmer(moteur, p.arete)
    assert ok.etat == "confirmee"


def test_une_arete_non_sensible_peut_etre_confirmee_par_le_systeme(moteur):
    p = moteur.proposer_arete(demande("utilise", inter("I-1"), NoeudRef("materiau", "bardeau-a")), par="a", quand=T0)
    assert not p.arete.sensible
    ok = moteur.confirmer_arete(p.arete.arete_id, par="systeme", mode="systeme", role=None, raison=None, quand=T0)
    assert ok.etat == "confirmee"


def test_double_confirmation_et_confirmation_apres_rejet_sont_refusees(moteur):
    p = moteur.proposer_arete(demande("possede", client("c1"), propriete("p1")), par="a", quand=T0)
    confirmer(moteur, p.arete)
    with pytest.raises(ErreurMnemo, match=codes.ARETE_TRANSITION):
        confirmer(moteur, p.arete)
    q = moteur.proposer_arete(demande("possede", client("c2"), propriete("p2")), par="a", quand=T0)
    moteur.rejeter_arete(q.arete.arete_id, raison="pas le bon client", quand=T0, **HUMAIN)
    with pytest.raises(ErreurMnemo, match=codes.ARETE_TRANSITION):
        confirmer(moteur, q.arete)
    with pytest.raises(ErreurMnemo, match=codes.ARETE_TRANSITION):  # une arête rejetée ne se ferme pas
        moteur.fermer_arete(q.arete.arete_id, "2026-06-01", raison="x", quand=T0, **HUMAIN)


def test_fermer_une_arete_pose_la_fin_de_validite_sans_rien_reecrire(moteur):
    p = moteur.proposer_arete(
        demande("possede", client("c1"), propriete("p1"), valide_de="2026-01-01"), par="a", quand=T0
    )
    with pytest.raises(ErreurMnemo, match=codes.ARETE_TRANSITION):  # un brouillon n'a pas de validité à fermer
        moteur.fermer_arete(p.arete.arete_id, "2026-06-01", raison="vendu", quand=T0, **HUMAIN)
    confirmer(moteur, p.arete)
    with pytest.raises(ErreurMnemo, match=codes.ENTREE_INVALIDE):  # la fin doit suivre le début
        moteur.fermer_arete(p.arete.arete_id, "2026-01-01", raison="vendu", quand=T0, **HUMAIN)
    f = moteur.fermer_arete(p.arete.arete_id, "2026-06-01", raison="propriété vendue", quand=T0, **HUMAIN)
    assert f.etat == "fermee" and f.valide_a == "2026-06-01"
    with pytest.raises(ErreurMnemo, match=codes.ARETE_TRANSITION):  # rien ne rouvre une arête fermée
        confirmer(moteur, p.arete)
    histoire = moteur.pourquoi(p.arete.arete_id)["historique"]
    assert [h["etat"] for h in histoire] == ["brouillon", "confirmee", "fermee"]


def test_proposer_deux_fois_la_meme_arete_ne_cree_rien_de_plus(moteur):
    d = demande("possede", client("c1"), propriete("p1"))
    a = moteur.proposer_arete(d, par="a", quand=T0)
    b = moteur.proposer_arete(d, par="b", quand="2026-11-02T00:00:00+00:00")
    assert a.creee and not b.creee and a.arete.arete_id == b.arete.arete_id
    assert moteur.etat()["aretes_par_etat"]["brouillon"] == 1
    autre = moteur.proposer_arete(
        demande("possede", client("c1"), propriete("p1"), valide_de="2026-02-01"), par="a", quand=T0
    )
    assert autre.creee and autre.arete.arete_id != a.arete.arete_id  # un autre début de validité est une autre relation


def test_arete_inconnue_et_noeud_inconnu_sont_nommes(moteur):
    with pytest.raises(ErreurMnemo, match=codes.ARETE_INCONNUE):
        moteur.confirmer_arete("0" * 32, quand=T0, raison=None, **HUMAIN)
    with pytest.raises(ErreurMnemo, match=codes.NOEUD_INCONNU):
        moteur.voisinage(inter("absent"), 1, a_la_date="2026-06-01")
    with pytest.raises(ErreurMnemo, match=codes.NOEUD_INCONNU):
        moteur.chemin(inter("absent"), inter("autre"), a_la_date="2026-06-01")


# ----------------------------------------------------------------------------------------------- validité et requêtes
def _petit_monde(moteur):
    """c1 possède p1 ; I-1 et I-2 sur p1 ; I-1 utilise b1 et b2 ; b1 fourni par f1 ; I-2 réalisée par eq1."""
    liste = [
        demande("possede", client("c1"), propriete("p1"), valide_de="2026-01-01"),
        demande("realisee_sur", inter("I-1"), propriete("p1"), valide_de="2026-02-01"),
        demande("realisee_sur", inter("I-2"), propriete("p1"), valide_de="2026-03-01"),
        demande("utilise", inter("I-1"), NoeudRef("materiau", "b1"), valide_de="2026-02-01"),
        demande("utilise", inter("I-1"), NoeudRef("materiau", "b2"), valide_de="2026-02-01"),
        demande("fourni_par", NoeudRef("materiau", "b1"), NoeudRef("fournisseur", "f1"), valide_de="2025-06-01"),
        demande("realisee_par", inter("I-2"), NoeudRef("equipe", "eq1"), valide_de="2026-03-01"),
    ]
    aretes = {}
    for d in liste:
        a = moteur.proposer_arete(d, par="a", quand=T0).arete
        aretes[(d.type, d.de.cle, d.vers.cle)] = confirmer(moteur, a)
    return aretes


def test_voisinage_a_k_sauts_avec_distances(moteur):
    _petit_monde(moteur)
    v = moteur.voisinage(client("c1"), 1, a_la_date="2026-12-01")
    assert {(n.type, d) for n, d in v.noeuds} == {("client", 0), ("propriete", 1)}
    v3 = moteur.voisinage(client("c1"), 3, a_la_date="2026-12-01")
    distances = {n.cle: d for n, d in v3.noeuds}
    assert distances[pseudo("p1")] == 1 and distances["I-1"] == 2 and distances["I-2"] == 2
    assert distances["b1"] == 3 and distances["b2"] == 3 and distances["eq1"] == 3 and "f1" not in distances
    assert not v3.tronque
    v4 = moteur.voisinage(client("c1"), 4, a_la_date="2026-12-01")
    assert "f1" in {n.cle for n, _ in v4.noeuds}


def test_k_est_borne(moteur):
    _petit_monde(moteur)
    for k in (0, 5, -1, 2.0, "2", True):
        with pytest.raises(ErreurMnemo, match=codes.REQUETE_TROP_LARGE):
            moteur.voisinage(client("c1"), k, a_la_date="2026-12-01")


def test_la_validite_dans_le_temps_borne_les_resultats(moteur):
    aretes = _petit_monde(moteur)
    avant = moteur.voisinage(client("c1"), 2, a_la_date="2026-02-15")  # I-2 n'existe pas encore (début 2026-03-01)
    assert {n.cle for n, _ in avant.noeuds} == {pseudo("c1"), pseudo("p1"), "I-1"}
    tres_tot = moteur.voisinage(client("c1"), 2, a_la_date="2025-12-31")
    assert {n.cle for n, _ in tres_tot.noeuds} == {pseudo("c1")}
    moteur.fermer_arete(
        aretes[("realisee_sur", "I-1", pseudo("p1"))].arete_id, "2026-05-01", raison="reprise", quand=T0, **HUMAIN
    )
    pendant = moteur.voisinage(client("c1"), 2, a_la_date="2026-04-30")
    apres = moteur.voisinage(
        client("c1"), 2, a_la_date="2026-05-01"
    )  # la fin est exclue : valide_a est le premier jour hors validité
    assert "I-1" in {n.cle for n, _ in pendant.noeuds} and "I-1" not in {n.cle for n, _ in apres.noeuds}


def test_les_brouillons_et_les_rejets_sont_exclus_sauf_demande_expresse(moteur):
    _petit_monde(moteur)
    brouillon = moteur.proposer_arete(demande("demande", client("c1"), inter("I-1")), par="a", quand=T0).arete
    rejetee = moteur.proposer_arete(demande("demande", client("c1"), inter("I-2")), par="a", quand=T0).arete
    moteur.rejeter_arete(rejetee.arete_id, raison="erreur d'association", quand=T0, **HUMAIN)
    v = moteur.voisinage(client("c1"), 1, a_la_date="2026-12-01")
    assert {n.cle for n, _ in v.noeuds} == {pseudo("c1"), pseudo("p1")}
    avec = moteur.voisinage(client("c1"), 1, a_la_date="2026-12-01", inclure_brouillons=True)
    assert {n.cle for n, _ in avec.noeuds} == {pseudo("c1"), pseudo("p1"), "I-1"}
    assert next(a for a in avec.aretes if a.arete_id == brouillon.arete_id).etat == "brouillon"
    assert rejetee.arete_id not in {a.arete_id for a in avec.aretes}


def test_le_filtre_par_type_d_arete_et_la_troncature(moteur):
    _petit_monde(moteur)
    v = moteur.voisinage(inter("I-1"), 2, a_la_date="2026-12-01", types_arete=["utilise"])
    assert {n.cle for n, _ in v.noeuds} == {"I-1", "b1", "b2"}
    petit = moteur.voisinage(client("c1"), 4, a_la_date="2026-12-01", noeuds_max=3)
    assert petit.tronque and len(petit.noeuds) == 3
    plein = moteur.voisinage(client("c1"), 4, a_la_date="2026-12-01")
    assert not plein.tronque and len(plein.noeuds) == 8


def test_chemin_le_plus_court_et_absence_de_chemin(moteur):
    _petit_monde(moteur)
    c = moteur.chemin(client("c1"), NoeudRef("fournisseur", "f1"), a_la_date="2026-12-01")
    assert c is not None and c.longueur == 4
    assert [n.type for n in c.noeuds] == ["client", "propriete", "intervention", "materiau", "fournisseur"]
    assert moteur.chemin(client("c1"), NoeudRef("fournisseur", "f1"), a_la_date="2026-12-01", k_max=3) is None
    assert moteur.chemin(client("c1"), NoeudRef("fournisseur", "f1"), a_la_date="2026-01-15") is None  # avant I-1
    soi = moteur.chemin(client("c1"), client("c1"), a_la_date="2026-12-01")
    assert soi is not None and soi.longueur == 0
    moteur.poser_noeud("fournisseur", "f-isole", None, source_ref="test:s", par="a", quand=T0)
    assert moteur.chemin(client("c1"), NoeudRef("fournisseur", "f-isole"), a_la_date="2026-12-01") is None


def test_pourquoi_dit_la_source_l_origine_et_qui_a_confirme(moteur):
    p = moteur.proposer_arete(
        demande("possede", client("c1"), propriete("p1"), ref="bus:m2.profil_propriete_confirme"),
        par="agent:m10",
        quand=T0,
    ).arete
    avant = moteur.pourquoi(p.arete_id)
    assert "en attente de la confirmation d'une personne" in avant["explication"]
    moteur.confirmer_arete(
        p.arete_id,
        par="direction.fictive",
        mode="humain",
        role="admin",
        raison="Vérifié sur le dossier",
        quand="2026-11-02T09:00:00+00:00",
    )
    apres = moteur.pourquoi(p.arete_id)
    assert "bus:m2.profil_propriete_confirme" in apres["explication"]
    assert "direction.fictive" in apres["explication"] and "Vérifié sur le dossier" in apres["explication"]
    assert apres["arete"]["source"]["ref"] == "bus:m2.profil_propriete_confirme"
    with pytest.raises(ErreurMnemo, match=codes.ARETE_INCONNUE):
        moteur.pourquoi("f" * 32)


def test_la_file_d_attente_met_les_aretes_sensibles_d_abord(moteur):
    moteur.proposer_arete(demande("utilise", inter("I-1"), NoeudRef("materiau", "b1")), par="a", quand=T0)
    moteur.proposer_arete(demande("possede", client("c1"), propriete("p1")), par="a", quand=T0)
    file = moteur.en_attente()
    assert [a.sensible for a in file] == [True, False]
    assert moteur.etat()["aretes_sensibles_en_attente"] == 1


# ----------------------------------------------------------------------------------------------- append-only (SQL)
def test_les_trois_tables_sont_append_only(session):
    with session() as cnx:
        g = GrapheSql(cnx)
        a = g.proposer_arete(demande("possede", client("c1"), propriete("p1")), par="a", quand=T0).arete
    for instruction in (
        "UPDATE graphe_noeuds SET libelle = 'autre'",
        "DELETE FROM graphe_noeuds",
        "UPDATE graphe_aretes SET confiance = 'haute'",
        "DELETE FROM graphe_aretes",
        "UPDATE graphe_aretes_etats SET etat = 'confirmee'",
        "DELETE FROM graphe_aretes_etats",
    ):
        with pytest.raises(DBAPIError, match="immuable"), session() as cnx:
            cnx.execute(text(instruction))
    with session() as cnx:
        assert GrapheSql(cnx).arete(a.arete_id).etat == "brouillon"


def test_une_transition_perimee_n_est_pas_appliquee_deux_fois(session):
    """Deux confirmations simultanées : la seconde lit encore « brouillon » mais l'INSERT conditionnel la refuse."""
    with session() as cnx:
        g = GrapheSql(cnx)
        a = g.proposer_arete(demande("possede", client("c1"), propriete("p1")), par="a", quand=T0).arete
        g.confirmer_arete(a.arete_id, quand=T0, raison=None, **HUMAIN)
        with pytest.raises(ErreurMnemo, match=codes.ARETE_TRANSITION):
            g._ajouter_etat(
                a.arete_id,
                "confirmee",
                attendu="brouillon",
                par="x",
                mode="humain",
                role="admin",
                raison=None,
                quand=T0,
            )
        nb = cnx.execute(text("SELECT count(*) FROM graphe_aretes_etats WHERE etat = 'confirmee'")).scalar_one()
        assert nb == 1


def test_une_arete_est_unique_par_type_extremites_et_debut(session):
    with session() as cnx:
        g = GrapheSql(cnx)
        a = g.proposer_arete(demande("possede", client("c1"), propriete("p1")), par="a", quand=T0).arete
        with pytest.raises(DBAPIError):
            cnx.execute(
                text(
                    "INSERT INTO graphe_aretes (arete_id, type, de_noeud, vers_noeud, valide_de, sensible, origine, "
                    "source_type, source_ref, confiance, cree_le, cree_par) "
                    "SELECT 'x' || substr(arete_id, 2), type, de_noeud, vers_noeud, valide_de, sensible, origine, "
                    "source_type, source_ref, confiance, cree_le, cree_par FROM graphe_aretes"
                )
            )
        assert a.arete_id


# ----------------------------------------------------------------------------------------------- parité des moteurs
def _graphe_aleatoire(moteur, graine: int):
    hasard = random.Random(graine)
    types = [
        ("client", pseudo),
        ("propriete", pseudo),
        ("intervention", lambda n: f"I-{n}"),
        ("materiau", lambda n: f"mat-{n}"),
        ("fournisseur", lambda n: f"f-{n}"),
        ("equipe", lambda n: f"eq-{n}"),
    ]
    noeuds = [NoeudRef(t, f(f"{t}{i}")) for i in range(6) for t, f in types]
    permis = [
        (t, a, b)
        for t, couples in schema.ARETES.items()
        for a, b in couples
        if a not in ("document", "decision") and b not in ("document", "decision")
    ]
    for _ in range(90):
        t, a, b = hasard.choice(permis)
        de = hasard.choice([n for n in noeuds if n.type == a])
        vers = hasard.choice([n for n in noeuds if n.type == b])
        if de == vers:
            continue
        debut = f"2026-{hasard.randint(1, 6):02d}-{hasard.randint(1, 28):02d}"
        arete = moteur.proposer_arete(demande(t, de, vers, valide_de=debut), par="a", quand=T0).arete
        tirage = hasard.random()
        if arete.etat != "brouillon":
            continue
        if tirage < 0.7:
            moteur.confirmer_arete(arete.arete_id, quand=T0, raison=None, **HUMAIN)
            if tirage < 0.25:
                moteur.fermer_arete(
                    arete.arete_id,
                    f"2026-{hasard.randint(7, 12):02d}-{hasard.randint(1, 28):02d}",
                    raison="fin",
                    quand=T0,
                    **HUMAIN,
                )
        elif tirage < 0.85:
            moteur.rejeter_arete(arete.arete_id, raison="erreur", quand=T0, **HUMAIN)
    return noeuds


@pytest.mark.parametrize("graine", [1, 2, 3])
def test_le_moteur_sql_et_le_double_rendent_exactement_les_memes_reponses(session, graine):
    memoire = GrapheMemoire()
    with session() as cnx:
        sql = GrapheSql(cnx)
        noeuds = _graphe_aleatoire(sql, graine)
        _graphe_aleatoire(memoire, graine)
        assert sql.etat()["aretes_par_etat"] == memoire.etat()["aretes_par_etat"]
        hasard = random.Random(graine)
        for _ in range(25):
            depart = hasard.choice(noeuds)
            date = f"2026-{hasard.randint(1, 12):02d}-{hasard.randint(1, 28):02d}"
            brouillons = hasard.random() < 0.3
            k = hasard.randint(1, 4)
            try:
                a = sql.voisinage(depart, k, a_la_date=date, inclure_brouillons=brouillons)
            except ErreurMnemo as exc:
                with pytest.raises(ErreurMnemo, match=exc.code):
                    memoire.voisinage(depart, k, a_la_date=date, inclure_brouillons=brouillons)
                continue
            b = memoire.voisinage(depart, k, a_la_date=date, inclure_brouillons=brouillons)
            assert a.vers_json() == b.vers_json()
            cible = hasard.choice(noeuds)
            if sql.noeud(cible.type, cible.cle) is None:  # jamais relié : les deux moteurs le disent pareil
                for m in (sql, memoire):
                    with pytest.raises(ErreurMnemo, match=codes.NOEUD_INCONNU):
                        m.chemin(depart, cible, a_la_date=date)
                continue
            ca = sql.chemin(depart, cible, a_la_date=date, inclure_brouillons=brouillons)
            cb = memoire.chemin(depart, cible, a_la_date=date, inclure_brouillons=brouillons)
            assert (ca.vers_json() if ca else None) == (cb.vers_json() if cb else None)
