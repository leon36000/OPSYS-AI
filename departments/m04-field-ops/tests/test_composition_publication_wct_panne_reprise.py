"""R2, composition (hypothèse, pas un bug affirmé) : la complétion DEVICE ATTEINT la vraie publication
`m4.travaux_termines`, puis une panne survient ; rien ne doit rester (ni WCT, ni événement, ni réclamation, ni trace),
la reprise après réouverture doit produire exactement un WCT et un événement, et le chantier voisin rester intact.

Vrais `Capacites.appeler` (mode `ombre`), vrais outils M4 (planification, pointages, dépôt de photo réelle),
vraie `opsys.evenements.publier` exécutée par un crochet qui ne fait que lever APRÈS elle. SQLite séquentiel, pool
libéré et façade recréée ; pas de crash OS, fsync, PostgreSQL, fournisseur ni consommation M6. Fictif.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m4_field_ops import cedule, etats, outbox
from m4_field_ops import registre as registre_m4
from sqlalchemy import select

from opsys import contexte, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
M4 = "m04-field-ops"
TYPE_WCT = "m4.travaux_termines"
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")  # chantier A, en panne
LEA = contexte.IdentiteAppelante(personne="lea.fictif", role="employee")    # chantier B, voisin
SEL = "sel-r2-fictif"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.508812, "longitude": -73.587834}
ATTESTATION = {"fictif": True, "appareil_id": "APP-R2-FICTIF"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
TABLES_COMPLETION = (REGISTRES, EVENEMENTS_SORTANTS, APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL)


class PanneApresPublication(RuntimeError):
    """Panne technique fictive, levée seulement après que la vraie publication a écrit sa ligne."""


@pytest.fixture
def cap(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        for personne in (MARC, LEA):
            identite.creer_personne(cnx, personne.personne, personne.personne.title(),
                                    "mot-de-passe-fictif-1234", ["employee"])
    yield _cap()
    stockage.liberer()


def _cap():
    departements = charger_departements(RACINE_DEPARTEMENTS)
    assert departements[M4].mode == "ombre"
    return Capacites(departements, stockage.transaction, filtre={M4}, memoire=False)


def _agent(cap, nom, arguments):
    reponse = executer_atomique(cap.index[nom][1], arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _appareil(cap, nom, arguments, appelante, cle):
    meta = idempotence.Meta(cle=cle, appareil=f"tel-{appelante.personne}-r2",
                            horodatage_appareil="2026-10-17T10:15:00-04:00")
    with contexte.appele_par_appareil(appelante):
        return cap.appeler(nom, arguments, meta)


def _sur_site(cap, lead_id, technicien) -> str:
    """Agent : planifie, consentement GPS, départ, arrivée et départ du site (comme test_acces_par_intervention)."""
    plan = _agent(cap, "m4_planifier_intervention", {
        "contrat": {"lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale", "ville": VILLE,
                    "canal": "telephone", "contact": {"nom": "Client fictif", "telephone": "0102030405"},
                    "urgence_declaree": False},
        "marqueur": {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
                     "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32},
        "horodatage": "2025-06-02T07:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": [technicien], "fenetres_disponibles": [FENETRE],
    })
    iid = plan["intervention_id"]
    _agent(cap, "m4_definir_consentement_gps", {
        "technicien_id": technicien, "action": "donne", "horodatage": "2025-06-02T06:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test", "preuve": {"fictif": True, "reference": "c"},
    })
    _agent(cap, "m4_demarrer_route", {"intervention_id": iid, "technicien_id": technicien,
                                      "horodatage": "2025-06-02T07:30:00+00:00"})
    for action, horodatage in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        _agent(cap, "m4_pointer", {
            "intervention_id": iid, "technicien_id": technicien, "action": action, "horodatage": horodatage,
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL})
    return iid


def _referentiel():
    return {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _completion(iid, photo, notes="RAS fictif."):
    return {"intervention_id": iid, "horodatage": "2025-06-02T11:35:00+00:00",
            "preuves_completion": {"checklist_complete": True, "photos_apres": [photo], "notes": notes,
                                   "signature": None}}


def _tables(*tables):
    with stockage.transaction() as cnx:
        return {t.name: [dict(r) for r in cnx.execute(select(t).order_by(*t.primary_key.columns)).mappings()]
                for t in tables}


def _ajouts_sans_reecriture(avant, apres):
    ajouts = {}
    for table, lignes in avant.items():
        assert all(ligne in apres[table] for ligne in lignes), f"{table} : rien d'antérieur réécrit"
        ajouts[table] = [ligne for ligne in apres[table] if ligne not in lignes]
    return ajouts


def _wcts(iid):
    with stockage.transaction():
        reg = registre_m4.Registre(stockage.maillons(M4, "principal"))
        return [w for _, w in outbox.lire_outbox(reg) if w["intervention_id"] == iid]


def _evenements(iid):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE_WCT)
                             .order_by(EVENEMENTS_SORTANTS.c.evenement_id)).mappings().all()
    return [dict(ligne) for ligne in lignes if stockage.codec.decoder(ligne["charge"])["intervention_id"] == iid]


def _statut(iid):
    with stockage.transaction():
        return etats.statut_courant(registre_m4.Registre(stockage.maillons(M4, "principal")), iid)


def test_panne_apres_vraie_publication_wct_rollback_puis_reprise_exacte_sans_toucher_le_voisin(
        cap, monkeypatch, deposer_photo_test):
    i_b = _sur_site(cap, "L-R2-VOISIN-B", LEA.personne)
    i_a = _sur_site(cap, "L-R2-PANNE-A", MARC.personne)
    deposer = {"m4_deposer_fichier": cap.index["m4_deposer_fichier"][1]}
    photo_a, photo_b = deposer_photo_test(deposer), deposer_photo_test(deposer)

    # Voisin B : complété et committé d'abord, par son propre appareil.
    avant_b = _tables(*TABLES_COMPLETION)
    fini_b = _appareil(cap, "m4_completer_intervention", _completion(i_b, photo_b), LEA, "r2-b")
    assert fini_b["ok"] and fini_b["resultat"]["accepte"] is True, fini_b
    delta_b = _ajouts_sans_reecriture(avant_b, _tables(*TABLES_COMPLETION))
    assert len(delta_b[REGISTRES.name]) == len(delta_b[EVENEMENTS_SORTANTS.name]) == 1
    (wct_b,) = _wcts(i_b)
    (evenement_b,) = _evenements(i_b)
    statut_b = _statut(i_b)
    assert statut_b == "completed_pending_review" and evenement_b["evenement_id"] == wct_b["wct_id"]

    statut_a = _statut(i_a)
    assert statut_a == "sur_site" and _wcts(i_a) == [] and _evenements(i_a) == []
    affaires_avant = _tables(REGISTRES, EVENEMENTS_SORTANTS)
    audit_avant = _tables(APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL)

    publier_original = evenements.publier
    atteintes = []

    def publier_puis_panne(type_evenement, producteur, charge, *, evenement_id=None):
        ident = publier_original(type_evenement, producteur, charge, evenement_id=evenement_id)
        if type_evenement == TYPE_WCT and charge.get("intervention_id") == i_a:
            cnx = stockage.connexion_courante()
            assert cnx is not None and cnx.in_transaction()
            ligne = cnx.execute(select(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.evenement_id == ident)).mappings().one()
            assert ident == charge["wct_id"] and ligne["producteur"] == M4 and ligne["type_evenement"] == TYPE_WCT
            assert stockage.codec.decoder(ligne["charge"]) == dict(charge)
            reg = registre_m4.Registre(stockage.maillons(M4, "principal"))
            assert [w for _, w in outbox.lire_outbox(reg) if w["intervention_id"] == i_a] == [dict(charge)]
            atteintes.append(ident)
            raise PanneApresPublication("panne fictive après publication WCT")
        return ident

    corps_a, cle_a = _completion(i_a, photo_a), "r2-a"
    try:
        monkeypatch.setattr(evenements, "publier", publier_puis_panne)
        with pytest.raises(PanneApresPublication):
            _appareil(cap, "m4_completer_intervention", corps_a, MARC, cle_a)
    finally:
        monkeypatch.setattr(evenements, "publier", publier_original)
    assert evenements.publier is publier_original
    assert len(atteintes) == 1, "la vraie publication de A a été atteinte exactement une fois"

    # Rollback complet, lu par une nouvelle transaction : métier ET audit tels qu'avant la tentative.
    assert _tables(REGISTRES, EVENEMENTS_SORTANTS) == affaires_avant
    assert _tables(APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL) == audit_avant, \
        "aucune réclamation, aucune trace de validation au départ pour une exécution annulée"
    assert _statut(i_a) == statut_a and _wcts(i_a) == [] and _evenements(i_a) == []
    assert _wcts(i_b) == [wct_b] and _evenements(i_b) == [evenement_b] and _statut(i_b) == statut_b

    # Réouverture : moteur libéré, Capacites neuve, même clé et même corps original.
    moteur_avant = stockage.moteur()
    stockage.liberer()
    cap_neuve = _cap()
    assert stockage.moteur() is not moteur_avant
    avant_reprise = _tables(*TABLES_COMPLETION)
    reprise = _appareil(cap_neuve, "m4_completer_intervention", corps_a, MARC, cle_a)
    assert reprise["ok"] and reprise["resultat"]["accepte"] is True and reprise["rejoue"] is False, reprise
    delta_a = _ajouts_sans_reecriture(avant_reprise, _tables(*TABLES_COMPLETION))
    assert {t: len(lignes) for t, lignes in delta_a.items()} == {
        t: len(lignes) for t, lignes in delta_b.items()
    }, "la reprise ne duplique ni transition, ni événement, ni trace d'audit de la complétion témoin"
    (ligne_a,) = delta_a[REGISTRES.name]
    assert ligne_a["departement"] == M4 and ligne_a["registre"] == "principal"
    maillon_a = stockage.codec.decoder(ligne_a["maillon"])
    assert maillon_a["intervention_id"] == i_a and maillon_a["statut"] == "completed_pending_review"
    (wct_a,) = _wcts(i_a)
    (evenement_a,) = _evenements(i_a)
    assert reprise["resultat"]["resultat"]["wct_id"] == wct_a["wct_id"] == evenement_a["evenement_id"]
    assert maillon_a[outbox.CLE_WCT] == wct_a and delta_a[EVENEMENTS_SORTANTS.name] == [evenement_a]
    assert wct_a["wct_id"] not in atteintes, "le WCT annulé n'a laissé aucun fantôme"
    assert _statut(i_a) == "completed_pending_review"
    apres_reprise = _tables(REGISTRES, EVENEMENTS_SORTANTS)
    for table, lignes in affaires_avant.items():
        assert all(ligne in apres_reprise[table] for ligne in lignes), f"{table} : rien d'antérieur réécrit"
    assert len(apres_reprise["evenements_sortants"]) == len(affaires_avant["evenements_sortants"]) + 1

    # Rejeu exact : réponse durable identique, aucun nouveau maillon ni événement ni réclamation.
    audit_reprise = _tables(APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL)
    rejeu = _appareil(cap_neuve, "m4_completer_intervention", corps_a, MARC, cle_a)
    assert rejeu == {**reprise, "rejoue": True}
    assert _tables(REGISTRES, EVENEMENTS_SORTANTS) == apres_reprise
    assert _tables(APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL) == audit_reprise

    # Même clé, autre corps : refus nommé, aucun effet.
    conflit = _appareil(cap_neuve, "m4_completer_intervention", _completion(i_a, photo_a, "Autre corps fictif."),
                        MARC, cle_a)
    assert conflit["ok"] is False and conflit["erreur"] == "mutation_conflit", conflit
    assert _tables(REGISTRES, EVENEMENTS_SORTANTS) == apres_reprise
    assert _tables(APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL) == audit_reprise

    assert _wcts(i_b) == [wct_b] and _evenements(i_b) == [evenement_b] and _statut(i_b) == statut_b
    assert len(_wcts(i_a)) == 1 and len(_evenements(i_a)) == 1
