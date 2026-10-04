"""Brouillons AP chiffrés : les fixtures et les personnes restent fictives."""

from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import threading

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text, update

from opsys import etat, fusion_ap, fusion_pdf, stockage
from opsys.stockage.schema import (
    FUSION_AP_BROUILLONS,
    FUSION_AP_COMMANDES,
    FUSION_COMMANDES,
    FUSION_LOTS,
    FUSION_PDF_LOTS,
    FUSION_PDF_QUOTA,
    PERSONNES,
    REGISTRES,
)


def _facture_pdf_fictive(unique: str = "") -> bytes:
    sortie = io.BytesIO()
    pdf = canvas.Canvas(sortie, invariant=1)
    pdf.setTitle(f"Facture fournisseur fictive {unique}")
    pdf.drawString(40, 780, "FOURNISSEUR FICTIF — EXEMPLE UNIQUEMENT")
    pdf.drawString(40, 750, "Facture no: FICTIF-2042")
    pdf.drawString(40, 730, "Date: 2026-10-01")
    pdf.drawString(40, 710, "Bon de commande: PO-FICTIF-7")
    pdf.drawString(40, 670, "Sous-total: 100.00 CAD")
    pdf.drawString(40, 650, "TPS: 5.00 CAD")
    pdf.drawString(40, 630, "TVQ: 9.98 CAD")
    pdf.drawString(40, 610, "Total: 114.98 CAD")
    pdf.showPage()
    pdf.save()
    return sortie.getvalue()


def _pdf_prete(acteur: str, mutation_id: str = "ap-pdf-fictif-1") -> dict:
    lot = fusion_pdf.creer(
        stockage.transaction,
        acteur,
        mutation_id=mutation_id,
        pdf_octets=_facture_pdf_fictive(mutation_id),
    )
    return fusion_pdf.preparer(stockage.transaction, acteur, lot["lot_id"], lot["revision"])


def _creer_brouillon_fictif(acteur: str, suffixe: str) -> dict:
    pdf = _pdf_prete(acteur, f"ap-pdf-fictif-{suffixe}")
    resultat = fusion_pdf.lire_resultat(stockage.transaction, acteur, pdf["lot_id"])
    return fusion_ap.enregistrer(
        stockage.transaction,
        acteur,
        pdf["lot_id"],
        mutation_id=f"ap-brouillon-fictif-{suffixe}",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=_payload(resultat),
    )


def _payload(resultat: dict, *, total: str = "114.98 CAD") -> dict:
    fragment = resultat["pages"][0]["fragments"][0]
    return {
        "schema_version": 1,
        "champs": {
            "fournisseur": "FOURNISSEUR FICTIF",
            "numero": "FICTIF-2042",
            "date": "2026-10-01",
            "po": "PO-FICTIF-7",
            "sous_total_imprime": "100.00 CAD",
            "taxe_imprimee": "TPS: 5.00 CAD; TVQ: 9.98 CAD",
            "total_imprime": total,
            "devise": "CAD",
        },
        "citations": {
            cle: [{"page": 1, "fragment_id": fragment["id"], "fragment_sha256": fragment["sha256"]}]
            for cle in (
                "fournisseur",
                "numero",
                "date",
                "po",
                "sous_total_imprime",
                "taxe_imprimee",
                "total_imprime",
                "devise",
            )
        },
    }


def test_brouillon_ap_chiffre_cite_idempotent_et_sans_ecriture_comptable(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"a" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    payload = _payload(resultat)

    meta = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-1",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=payload,
    )
    assert meta["statut"] == "A_REVOIR" and meta["revision"] == 1
    assert "champs" not in meta and "citations" not in meta and "cipher" not in meta
    assert (
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-1",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=payload,
        )
        == meta
    )

    modifie = _payload(resultat, total="114.98 CAD — corrigé par humain")
    courant = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-1b",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=1,
        proposition=modifie,
    )
    reprise = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-1",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=payload,
    )
    assert courant["revision"] == 2
    assert reprise["revision"] == 2 and reprise["revision_appliquee"] == 1

    prive = fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])
    assert prive["champs"] == modifie["champs"]
    assert prive["citations"] == modifie["citations"]
    with stockage.transaction() as cnx:
        lot = cnx.execute(select(FUSION_PDF_LOTS)).mappings().one()
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        quota = cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one()
        journal = etat.lire_journal(cnx)
        assert (
            brouillon["proposition_cipher"]
            != base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        )
        assert "FICTIF-2042" not in brouillon["proposition_cipher"]
        assert quota["octets_cipher"] == (
            lot["source_cipher_octets"] + lot["resultat_cipher_octets"] + brouillon["proposition_cipher_octets"]
        )
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 2
        assert all("FICTIF-2042" not in row["details"] and "114.98" not in row["details"] for row in journal)


def test_liste_a_revoir_bornee_metadonnees_seulement_et_sans_ecriture(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"l" * 32).decode())
    premiers = [_creer_brouillon_fictif(nathan, suffixe) for suffixe in ("liste-a", "liste-b")]
    avant = None
    with stockage.transaction() as cnx:
        avant = (
            cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
        )

    monkeypatch.setattr(fusion_ap, "_dechiffrer", lambda *_: pytest.fail("liste a déchiffré un brouillon"))
    rows = fusion_ap.lister_a_revoir(stockage.transaction, nathan)
    assert len(rows) == 2
    assert {row["lot_id"] for row in rows} == {row["lot_id"] for row in premiers}
    assert all(row["etat_source"] == "A_REVALIDER" and row["statut"] == "A_REVOIR" for row in rows)
    assert all(
        set(row) == {"lot_id", "revision", "statut", "cree_le", "modifie_le", "etat_source"}
        for row in rows
    )
    assert all("fournisseur" not in row and "source_sha256" not in row and "cipher" not in row for row in rows)
    with stockage.transaction() as cnx:
        apres = (
            cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one(),
            cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one(),
            cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
        )
    assert apres == avant
    with pytest.raises(fusion_ap.FusionAPErreur) as depassement:
        fusion_ap.lister_a_revoir(stockage.transaction, nathan, limite=1)
    assert depassement.value.code == "LISTE_AP_DEPASSE_QUOTA"
    with pytest.raises(fusion_ap.FusionAPErreur) as invalide:
        fusion_ap.lister_a_revoir(stockage.transaction, nathan, limite=fusion_pdf.NB_LOTS_MAX + 1)
    assert invalide.value.code == "LIMITE_INVALIDE"


def test_liste_a_revoir_marque_source_changee_et_etat_malforme_indisponibles(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"m" * 32).decode())
    draft = _creer_brouillon_fictif(nathan, "liste-stale")
    with stockage.transaction() as cnx:
        cnx.execute(
            update(FUSION_PDF_LOTS)
            .where(FUSION_PDF_LOTS.c.lot_id == draft["lot_id"])
            .values(source_sha256="0" * 64)
        )
    row = fusion_ap.lister_a_revoir(stockage.transaction, nathan)[0]
    assert row["lot_id"] == draft["lot_id"]
    assert row["etat_source"] == "INDISPONIBLE"
    assert set(row) == {"lot_id", "revision", "statut", "cree_le", "modifie_le", "etat_source"}

    base = {
        "ap_lot_id": draft["lot_id"], "ap_statut": "A_REVOIR", "ap_revision": 1,
        "ap_revision_pdf": 1, "ap_version_format": 1, "ap_source_sha256": "a" * 64,
        "ap_configuration_sha256": "b" * 64, "ap_extracteur": fusion_pdf.EXTRACTEUR,
        "ap_cree_le": "2026-10-03T00:00:00+00:00", "ap_modifie_le": "2026-10-03T00:00:00+00:00",
        "pdf_lot_id": draft["lot_id"], "pdf_statut": "EXTRAIT_PREPARATOIRE", "pdf_revision": 1,
        "pdf_version_format": 1, "pdf_type_source": "pdf_natif", "pdf_classe": "FINANCIAL",
        "pdf_source_sha256": "a" * 64, "pdf_configuration_sha256": "b" * 64,
        "pdf_extracteur": fusion_pdf.EXTRACTEUR, "pdf_modifie_le": "2026-10-03T00:00:00+00:00",
    }
    base["ap_statut"] = "ETAT_INCONNU"
    assert fusion_ap._projection_liste_ap(base)["etat_source"] == "INDISPONIBLE"
    base["ap_statut"] = "A_REVOIR"
    base["pdf_lot_id"] = None
    assert fusion_ap._projection_liste_ap(base)["etat_source"] == "INDISPONIBLE"


def test_brouillon_ap_cas_citation_invalide_rejeu_mutation_et_quota_rollback(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"b" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    payload = _payload(resultat)
    trop_long = json.loads(json.dumps(payload))
    trop_long["champs"]["numero"] = "x" * 129
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-long",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=trop_long,
        )
    assert erreur.value.code == "PROPOSITION_INVALIDE"
    cite_fausse = json.loads(json.dumps(payload))
    cite_fausse["citations"]["total_imprime"][0]["fragment_sha256"] = "0" * 64
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-2",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=cite_fausse,
        )
    assert erreur.value.code == "CITATION_INVALIDE"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0

    meta = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-2",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=payload,
    )
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-2",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=_payload(resultat, total="999999.00 CAD"),
        )
    assert erreur.value.code == "CONFLIT_MUTATION"

    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-stale",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=_payload(resultat, total="114.99 CAD"),
        )
    assert erreur.value.code == "CONFLIT_REVISION"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 1
        assert cnx.execute(select(FUSION_AP_BROUILLONS.c.revision)).scalar_one() == 1

    with stockage.transaction() as cnx:
        octets_apres_creation = cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one()
        cnx.execute(FUSION_PDF_QUOTA.update().values(octets_cipher=fusion_pdf.QUOTA_CIPHER_MAX))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-brouillon-3",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=meta["revision"],
            proposition=_payload(resultat, total="114.98 CAD revised"),
        )
    assert erreur.value.code == "PDF_QUOTA_ATTEINT"
    with stockage.transaction() as cnx:
        quota = cnx.execute(select(FUSION_PDF_QUOTA)).mappings().one()
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        assert octets_apres_creation < quota["octets_cipher"] == fusion_pdf.QUOTA_CIPHER_MAX
        assert brouillon["revision"] == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0


def test_brouillon_ap_cle_historique_et_autorisation_active(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"c" * 32).decode())
    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_CLE_PDF_OLD")
    monkeypatch.setenv("OPSYS_CLE_PDF_OLD", base64.b64encode(b"d" * 32).decode())
    monkeypatch.setenv("OPSYS_CLE_PDF_NEW", base64.b64encode(b"e" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    meta = fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="ap-brouillon-4",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=_payload(resultat),
    )
    monkeypatch.setenv("OPSYS_INGESTION_CLE_REFERENCE", "OPSYS_CLE_PDF_NEW")
    assert fusion_ap.lire(stockage.transaction, nathan, pdf["lot_id"]) == {
        cle: valeur for cle, valeur in meta.items() if cle != "revision_appliquee"
    }
    assert fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])["champs"]["numero"] == "FICTIF-2042"
    monkeypatch.setenv("OPSYS_CLE_PDF_OLD", base64.b64encode(b"x" * 32).decode())
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])
    assert erreur.value.code == "CIPHER_INVALIDE" and "FICTIF-2042" not in str(erreur.value)
    monkeypatch.setenv("OPSYS_CLE_PDF_OLD", base64.b64encode(b"d" * 32).decode())
    with stockage.transaction() as cnx:
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        assert brouillon["cle_reference"] == "OPSYS_CLE_PDF_OLD"
        from opsys import identite

        identite.creer_personne(cnx, "lecteur-fictif", "Lecteur fictif", "long-test-password-123", ["employee"])
    with pytest.raises(PermissionError):
        fusion_ap.lire_champs(stockage.transaction, "lecteur-fictif", pdf["lot_id"])
    with stockage.transaction() as cnx:
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        cnx.execute(FUSION_AP_BROUILLONS.update().values(proposition_cipher="!" + brouillon["proposition_cipher"][1:]))
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.lire_champs(stockage.transaction, nathan, pdf["lot_id"])
    assert erreur.value.code == "CIPHER_INVALIDE"


def test_migration_0020_additive_conserve_csv_et_pdf(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration-ap-fictive.db'}"
    try:
        with stockage.moteur(url).begin() as cnx:
            configuration = stockage._config()
            configuration.attributes["connection"] = cnx
            from alembic import command

            command.upgrade(configuration, "0019")
            cnx.execute(text("UPDATE fusion_quota SET lots=3,octets_cipher=321 WHERE id=1"))
            cnx.execute(text("UPDATE fusion_pdf_quota SET lots=1,octets_cipher=432 WHERE id=1"))
            cnx.execute(
                FUSION_LOTS.insert().values(
                    lot_id="csv-fictif-conserve",
                    acteur="admin-fictif",
                    mutation_id="csv-ancien",
                    empreinte_requete="e" * 64,
                    cle_deduplication="f" * 64,
                    compte_interne_id="compte-fictif",
                    devise="CAD",
                    mapping_colonnes="{}",
                    source_sha256="a" * 64,
                    source_octets=1,
                    source_nonce="nonce-fictif",
                    source_cipher="cipher-fictif",
                    source_cipher_octets=17,
                    resultat_nonce=None,
                    resultat_cipher=None,
                    resultat_cipher_octets=0,
                    cle_reference="OPSYS_INGESTION_CLE",
                    version_format=1,
                    snapshot_version=0,
                    snapshot_empreinte=None,
                    statut="RECU",
                    revision=1,
                    curseur=0,
                    total_lignes=None,
                    nombre_propositions=0,
                    verdict=None,
                    cree_le="fictif",
                    modifie_le="fictif",
                )
            )
            cnx.execute(
                FUSION_COMMANDES.insert().values(
                    acteur="admin-fictif",
                    mutation_id="csv-ancien",
                    empreinte_requete="e" * 64,
                    lot_id="csv-fictif-conserve",
                    cree_le="fictif",
                )
            )
            cnx.execute(
                FUSION_PDF_LOTS.insert().values(
                    lot_id="00000000-0000-4000-8000-000000000020",
                    acteur="admin-fictif",
                    mutation_id="pdf-ancien",
                    empreinte_requete="a" * 64,
                    cle_deduplication="b" * 64,
                    type_source="pdf_natif",
                    classe="FINANCIAL",
                    extracteur="pypdf-6.19.0/pdf-natif-1",
                    configuration_sha256="c" * 64,
                    source_sha256="d" * 64,
                    source_octets=1,
                    source_nonce="nonce-fictif",
                    source_cipher="cipher-fictif",
                    source_cipher_octets=17,
                    resultat_nonce=None,
                    resultat_cipher=None,
                    resultat_cipher_octets=0,
                    cle_reference="OPSYS_INGESTION_CLE",
                    version_format=1,
                    statut="RECU",
                    revision=1,
                    total_pages=0,
                    code=None,
                    cree_le="fictif",
                    modifie_le="fictif",
                )
            )
        stockage.migrer(url)
        from alembic.script import ScriptDirectory

        revision_tete = ScriptDirectory.from_config(stockage._config()).get_current_head()
        assert stockage.revision_courante(url) == revision_tete
        with stockage.moteur(url).connect() as cnx:
            assert tuple(cnx.execute(text("SELECT lots,octets_cipher FROM fusion_quota")).one()) == (3, 321)
            assert tuple(cnx.execute(text("SELECT lots,octets_cipher FROM fusion_pdf_quota")).one()) == (1, 432)
            assert cnx.execute(text("SELECT mutation_id FROM fusion_pdf_lots")).scalar_one() == "pdf-ancien"
            assert cnx.execute(text("SELECT mutation_id FROM fusion_lots")).scalar_one() == "csv-ancien"
            assert cnx.execute(text("SELECT mutation_id FROM fusion_commandes")).scalar_one() == "csv-ancien"
            assert cnx.execute(text("SELECT count(*) FROM fusion_ap_brouillons")).scalar_one() == 0
    finally:
        stockage.liberer()


def test_deux_admins_concurrents_gagnent_un_seul_cas(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"g" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    barriere = threading.Barrier(2)
    with stockage.transaction() as cnx:
        from opsys import identite

        identite.creer_personne(cnx, "admin-fictif-2", "Admin fictif 2", "mot-de-passe-admin-2-long", ["admin"])

    def ecrire(acteur, mutation, proposition):
        try:
            barriere.wait(timeout=2)
            return fusion_ap.enregistrer(
                stockage.transaction,
                acteur,
                pdf["lot_id"],
                mutation_id=mutation,
                revision_pdf_attendue=pdf["revision"],
                revision_attendue=0,
                proposition=proposition,
            )
        except fusion_ap.FusionAPErreur as exc:
            return exc.code

    propositions = [_payload(resultat), _payload(resultat, total="114.98 CAD revu")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(ecrire, acteur, f"concurrent-{i}", value)
            for i, (acteur, value) in enumerate(zip((nathan, "admin-fictif-2"), propositions, strict=True))
        ]
        resultats = [future.result(timeout=5) for future in futures]
    assert sum(isinstance(item, dict) for item in resultats) == 1
    assert sum(isinstance(item, str) and item in {"CONFLIT_REVISION", "STOCKAGE_OCCUPE"} for item in resultats) == 1
    with stockage.transaction() as cnx:
        brouillon = cnx.execute(select(FUSION_AP_BROUILLONS)).mappings().one()
        assert brouillon["revision"] == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0


def test_revocation_apres_ecriture_annule_brouillon_et_quota(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"h" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    from opsys import identite as personne

    original = personne.personne_active

    def revoquer_apres_journal(cnx, acteur):
        active = original(cnx, acteur)
        if cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one():
            cnx.execute(PERSONNES.update().where(PERSONNES.c.identifiant == acteur).values(actif=False))
            return None
        return active

    monkeypatch.setattr(personne, "personne_active", revoquer_apres_journal)
    with pytest.raises(PermissionError):
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="ap-revoque-commit",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=0,
            proposition=_payload(resultat),
        )
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(FUSION_LOTS)).scalar_one() == 0
        # Le PDF prêt possède deux traces candidates M10; AP n’écrit aucun autre registre.
        provenance = (REGISTRES.c.departement == "m10-memoire") & (REGISTRES.c.registre == "documents")
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(provenance)).scalar_one() == 2
        assert cnx.execute(select(func.count()).select_from(REGISTRES).where(~provenance)).scalar_one() == 0
        assert cnx.execute(select(PERSONNES.c.actif).where(PERSONNES.c.identifiant == nathan)).scalar_one() is True


def test_quota_commandes_ferme_apres_128_mutations(nathan, monkeypatch):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"i" * 32).decode())
    pdf = _pdf_prete(nathan)
    resultat = fusion_pdf.lire_resultat(stockage.transaction, nathan, pdf["lot_id"])
    fusion_ap.enregistrer(
        stockage.transaction,
        nathan,
        pdf["lot_id"],
        mutation_id="commande-initiale",
        revision_pdf_attendue=pdf["revision"],
        revision_attendue=0,
        proposition=_payload(resultat),
    )
    with stockage.transaction() as cnx:
        cnx.execute(
            FUSION_AP_COMMANDES.insert(),
            [
                {
                    "lot_id": pdf["lot_id"],
                    "acteur": nathan,
                    "mutation_id": f"commande-{index:03d}",
                    "empreinte_requete": f"{index:064x}",
                    "revision_resultat": 1,
                    "cree_le": "fictif",
                }
                for index in range(fusion_ap.MAX_COMMANDES_PAR_LOT - 1)
            ],
        )
        avant_quota = cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one()
    with pytest.raises(fusion_ap.FusionAPErreur) as erreur:
        fusion_ap.enregistrer(
            stockage.transaction,
            nathan,
            pdf["lot_id"],
            mutation_id="commande-128",
            revision_pdf_attendue=pdf["revision"],
            revision_attendue=1,
            proposition=_payload(resultat),
        )
    assert erreur.value.code == "AP_COMMANDES_QUOTA_ATTEINT"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_BROUILLONS)).scalar_one() == 1
        assert cnx.execute(select(FUSION_PDF_QUOTA.c.octets_cipher)).scalar_one() == avant_quota
        assert cnx.execute(select(func.count()).select_from(FUSION_AP_COMMANDES)).scalar_one() == 128
