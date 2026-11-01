"""Outillage QA de l'ingestion d'onboarding (tests seulement, jamais une capacité livrée).

- `pdf_texte` : un PDF né numérique minimal (Helvetica, WinAnsi), généré ici à partir du texte fictif du corpus ;
- `extracteur_pdf_en_processus` : le CODE du worker natif (`fusion_pdf_worker._extraire`, pypdf) exécuté dans le
  processus de test, parce que bubblewrap manque dans le bac à sable ; la production passe par le worker isolé ;
- `adaptateur_simule` : le fournisseur d'extraction SIMULÉ et déterministe (étiquettes « Clé : valeur ») raccordé au
  port d'extraction par les tests ; `declarer_fournisseur_simule` le déclare, l'active et le sélectionne au registre de
  fournisseurs, sous la vraie politique de licence.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import Path

CORPUS = Path(__file__).with_name("ingestion_onboarding")
IDENTIFIANT_SIMULE = "llm.qa-extraction-simulee"
POINT_ACCES_SIMULE = "module:opsys_qa.extracteur_simule"
IDENTITE = {"nom_legal": "Gouttières Fictives Synergy inc.", "tps": "987654321 RT 0001", "tvq": "9876543210 TQ 0001"}


def _echapper(texte: str) -> bytes:
    brut = texte.encode("cp1252")
    return brut.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf_texte(texte: str) -> bytes:
    """PDF 1.4 d'une page : une ligne de texte par ligne de `texte` (aucune image, aucun script)."""
    flux = [b"BT /F1 10 Tf 40 800 Td 12 TL"]
    for ligne in texte.splitlines():
        flux.append(b"(" + _echapper(ligne) + b") Tj T*")
    flux.append(b"ET")
    contenu = b"\n".join(flux)
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(contenu)).encode() + b" >>\nstream\n" + contenu + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    sortie = io.BytesIO()
    sortie.write(b"%PDF-1.4\n")
    positions = []
    for numero, objet in enumerate(objets, 1):
        positions.append(sortie.tell())
        sortie.write(f"{numero} 0 obj\n".encode() + objet + b"\nendobj\n")
    xref = sortie.tell()
    sortie.write(f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode())
    for position in positions:
        sortie.write(f"{position:010d} 00000 n \n".encode())
    sortie.write(f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return sortie.getvalue()


def extracteur_pdf_en_processus(source: bytes) -> dict:
    from opsys import fusion_pdf_worker

    try:
        return {"ok": True, "resultat": fusion_pdf_worker._extraire(source)}
    except fusion_pdf_worker.RefusPDF as exc:
        return {"ok": False, "code": str(exc.args[0]) if exc.args else "PDF_MALFORME"}


def _cle(etiquette: str) -> str:
    simple = "".join(c for c in unicodedata.normalize("NFKD", etiquette) if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", simple).split())


def adaptateur_simule(pages, fournisseur) -> dict:
    """Lecture déterministe d'une facture étiquetée (« Émetteur : … », « Ligne : desc | qté | prix | montant »)."""
    valeurs: dict[str, str] = {}
    lignes = []
    for page in pages:
        for ligne in page["texte"].splitlines():
            if ":" not in ligne:
                continue
            etiquette, valeur = ligne.split(":", 1)
            cle, valeur = _cle(etiquette), valeur.strip()
            if cle == "ligne":
                description, quantite, prix, montant = (p.strip() for p in valeur.split("|"))
                lignes.append({"description": description, "quantite": quantite, "prix_unitaire": prix,
                               "montant": montant})
            else:
                valeurs.setdefault(cle, valeur)
    return {
        "schema": "opsys.facture/v1",
        "emetteur": {"nom": valeurs.get("emetteur"), "no_tps": valeurs.get("no tps"),
                     "no_tvq": valeurs.get("no tvq"), "adresse": valeurs.get("adresse emetteur")},
        "destinataire": {"nom": valeurs.get("facture a")},
        "numero": valeurs.get("numero"), "date": valeurs.get("date"), "echeance": valeurs.get("echeance"),
        "devise": valeurs.get("devise"), "lignes": lignes, "sous_total": valeurs.get("sous total"),
        "tps": valeurs.get("tps"), "tvq": valeurs.get("tvq"), "total": valeurs.get("total"),
    }


def raccorder_simule(monkeypatch) -> None:
    from opsys.ingestion_onboarding import port_extraction

    monkeypatch.setitem(port_extraction._ADAPTATEURS, POINT_ACCES_SIMULE, adaptateur_simule)


def declarer_fournisseur_simule(cnx, admin: str, *, selectionner: bool = True) -> None:
    from opsys.fournisseurs import registre

    if registre.profil_brut(cnx) is None:
        registre.declarer_profil(cnx, acteur=admin, usage_commercial=True, revenu_annuel_usd=1_500_000,
                                 territoires=["CA"], heberge_pour_tiers=False, revision_attendue=0)
    registre.configurer(cnx, acteur=admin, identifiant=IDENTIFIANT_SIMULE, declaration={
        "capacite": "llm", "mode": "local", "modele": "qa-simule-deterministe", "point_acces": POINT_ACCES_SIMULE,
        "residence_donnees": "local",
        "licence": {"code": "Code du dépôt OPSYS (QA)", "poids": None, "usage_commercial": "autorise",
                    "service_tiers": "autorise", "integration": "bibliotheque", "source": "tests OPSYS (fictif)"}})
    assert registre.activer(cnx, acteur=admin, identifiant=IDENTIFIANT_SIMULE).conforme
    if selectionner:
        registre.selectionner(cnx, acteur=admin, capacite="llm", identifiant=IDENTIFIANT_SIMULE)


def texte_corpus(chemin: str) -> str:
    return (CORPUS / chemin).read_text(encoding="utf-8")


def zip_onboarding(membres: dict[str, bytes]) -> bytes:
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom, octets in membres.items():
            archive.writestr(nom, octets)
    return sortie.getvalue()


def corpus_complet() -> dict[str, bytes]:
    """Le dépôt d'onboarding fictif complet (voir ingestion_onboarding/MANIFESTE.yaml)."""
    f1 = pdf_texte(texte_corpus("factures/F1-quincaillerie.txt"))
    membres = {
        "factures/F1-quincaillerie.pdf": f1,
        "factures/F2-materiaux.pdf": pdf_texte(texte_corpus("factures/F2-materiaux.txt")),
        "factures/F3-location-tvq.pdf": pdf_texte(texte_corpus("factures/F3-location-tvq.txt")),
        "factures/F4-peinture-sommes.txt": (CORPUS / "factures/F4-peinture-sommes.txt").read_bytes(),
        "factures/F5-emise-par-nous.txt": (CORPUS / "factures/F5-emise-par-nous.txt").read_bytes(),
        "factures/F6-date-future.txt": (CORPUS / "factures/F6-date-future.txt").read_bytes(),
        "factures/F7-sans-numero-tps.txt": (CORPUS / "factures/F7-sans-numero-tps.txt").read_bytes(),
        "copies/F1-quincaillerie-copie.pdf": f1,
        "copies/F1-quincaillerie.txt": (CORPUS / "factures/F1-quincaillerie.txt").read_bytes(),
        "autres/soumission-toiture.txt": (CORPUS / "autres/soumission-toiture.txt").read_bytes(),
        "autres/contrat-entretien.txt": (CORPUS / "autres/contrat-entretien.txt").read_bytes(),
        "autres/notes-reunion.txt": (CORPUS / "autres/notes-reunion.txt").read_bytes(),
        "clients/clients.csv": (CORPUS / "clients.csv").read_bytes(),
        "autres/photo-chantier.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        "autres/outil.exe": b"MZ" + b"\x00" * 32,
        "autres/faux.pdf": b"ceci n'est pas un PDF (fictif)\n",
        "__MACOSX/._F1-quincaillerie.pdf": b"\x00\x05\x16\x07",
    }
    return membres


def preparer_instance(tmp_path, monkeypatch, *, identite: bool = True, fournisseur: bool = True) -> str:
    """Base SQLite migrée, clé d'ingestion de test, personnes fictives, identité fiscale déclarée, fournisseur simulé
    déclaré + activé + sélectionné et raccordé, dossier de dépôt créé. Rend l'URL de la base."""
    import base64
    import os

    import yaml

    from opsys import identite as opsys_identite
    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'onboarding.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(os.urandom(32)).decode("ascii"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        opsys_identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                      ["nathan_owner", "admin"])
        opsys_identite.creer_personne(cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234",
                                      ["finance", "admin"])
        if fournisseur:
            declarer_fournisseur_simule(cnx, "nathan")
    if fournisseur:
        raccorder_simule(monkeypatch)
    dossier = stockage.dossier_opsys()
    (dossier / "imports" / "onboarding").mkdir(parents=True, exist_ok=True)
    if identite:
        (dossier / "entreprise.yaml").write_text(yaml.safe_dump({"identite_fiscale": IDENTITE}, allow_unicode=True),
                                                 encoding="utf-8")
    return url


def deposer_fichier(nom: str, octets: bytes) -> Path:
    from opsys.ingestion_onboarding import depot

    chemin = depot.dossier_depot() / nom
    chemin.write_bytes(octets)
    return chemin
