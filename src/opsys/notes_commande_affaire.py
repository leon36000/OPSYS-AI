"""Lecture humaine du rattachement M6 → M3 → M2 → M10, sans publication.

La cible attendue n'est pas une autorité. Chaque source est relue dans la même
transaction SQLite. Aucun ticket Core, rôle d'agent ou fait mémoire n'est créé.
"""
from __future__ import annotations

from . import stockage

MAX_SOURCES = 10000


class RattachementRefuse(ValueError):
    """Code fermé uniquement : aucune donnée métier dans le diagnostic."""


def _lire(departement, registre):
    source = stockage.maillons(departement, registre)
    if len(source) > MAX_SOURCES:
        raise RattachementRefuse("SOURCES-TROP-VOLUMINEUSES")
    lignes = list(source)
    if len(lignes) > MAX_SOURCES or any(type(m) is not dict for m in lignes):
        raise RattachementRefuse("SOURCE-INVALIDE")
    return lignes


def resoudre(note_id, revision, devis_attendu, affaire_attendue):
    """DTO minimal admin, à la version exacte ; un refus ne révèle aucune cible."""
    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts
    from m3_estimation import devis_durable
    from m6_material_control import besoins_prevus, notes_commande
    from m6_material_control import outils as m6
    from m10_memoire import affaire, amont
    from m10_memoire import registre as registre_m10

    try:
        # Avant toute lecture métier, même lorsque les arguments sont invalides.
        m6.autoriser_note_commande()
        cnx = stockage.connexion_courante()
        if cnx.dialect.name != "sqlite":
            raise RattachementRefuse("BACKEND-NON-QUALIFIE")
        if not notes_commande.entier(revision, 1):
            raise RattachementRefuse("REVISION-INVALIDE")
        if not isinstance(affaire_attendue, str) or not affaire.est_lead(affaire_attendue):
            raise RattachementRefuse("AFFAIRE-NON-PRISE-EN-CHARGE")
        notes = _lire("m06-material-control", notes_commande.REGISTRE)
        notes_commande.valider_registre(notes)
        note = notes_commande.lire(notes, note_id, revision)
        if note is None:
            raise RattachementRefuse("NOTE-INTROUVABLE")
        if note["devis_id"] != devis_attendu:
            raise RattachementRefuse("ANCRAGE-DIFFERENT")
        besoins = _lire("m06-material-control", "besoins_prevus")
        definitifs = [m for m in besoins if m.get("devis_id") == devis_attendu
                      and m.get("source") != besoins_prevus.SOURCE_ESTIMATION_M3]
        if len(definitifs) != 1 or definitifs[0].get("chantier_id") != note["chantier_id"]:
            raise RattachementRefuse("BESOIN-NON-CONCORDANT")
        devis = _lire("m03-estimation", "devis")
        lignes = [m for m in devis if m.get("devis_id") == devis_attendu]
        creations = [m for m in lignes if m.get("type_entree") == "devis_cree"]
        if len(creations) != 1 or lignes[0] != creations[0]:
            raise RattachementRefuse("DEVIS-ABSENT-OU-AMBIGU")
        creation = creations[0]
        # Le lecteur M3 fusionne les transitions ; elles ne peuvent changer la cible.
        if any(m.get("type_entree") not in {"devis_cree", "transition_devis"}
               or any(k in m and m[k] != creation.get(k) for k in ("lead_id", "chantier_id")) for m in lignes):
            raise RattachementRefuse("ANCRAGE-DEVIS-INVALIDE")
        etat, verdict = devis_durable.lire_devis(devis, devis_attendu)
        if verdict is not None or etat is None or etat.get("lead_id") != affaire_attendue:
            raise RattachementRefuse("ANCRAGE-DIFFERENT")
        if etat.get("chantier_id") is None:
            raise RattachementRefuse("CHANTIER-M3-NON-CONFIRME")
        if etat["chantier_id"] != note["chantier_id"]:
            raise RattachementRefuse("CHANTIER-DIFFERENT")
        crm = registre_m2.Registre(maillons=_lire("m02-revenue-crm", "principal"))
        if crm.valider_chaine() is not True:
            raise RattachementRefuse("SOURCE-M2-INVALIDE")
        if statuts.statut_courant(crm, affaire_attendue) is None:
            raise RattachementRefuse("LEAD-M2-ABSENT")
        memoire = registre_m10.Registre(maillons=_lire("m10-memoire", "evenements"))
        if memoire.valider_chaine()[0] is not True:
            raise RattachementRefuse("SOURCE-M10-INVALIDE")
        situation = amont.situation(affaire_attendue, memoire.lire())
        if not situation["origine_recue"]:
            raise RattachementRefuse("ORIGINE-M10-ABSENTE")
        return {"statut": "VERIFIE", "affaire_id": affaire_attendue, "revision": note["revision"],
                "source_index": note["index"], "source_hash": note["hash_maillon"],
                "origine": situation["origine"], "note_memorisee": False}
    except notes_commande.Refus as exc:
        return {"statut": "NON_VERIFIE", "code": "NOTE-"+exc.suffixe}
    except RattachementRefuse as exc:
        return {"statut": "NON_VERIFIE", "code": str(exc)}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"statut": "NON_VERIFIE", "code": "SOURCE-INVALIDE"}
