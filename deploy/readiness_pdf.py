"""Gate PDF opt-in : readiness existant + contrats SQLite/clé/worker isolé, sans écriture métier."""

from __future__ import annotations

import argparse
import os
import sys

import readiness
from sqlalchemy.engine import make_url

from opsys import fusion_csv, fusion_pdf, stockage

# Document fixe de zéro page, 233 octets sans donnée financière. Le refus exact prouve
# l'import du parseur et l'exécution du worker sous ses limites/namespaces. Le parent
# n'importe jamais pypdf et n'effectue aucune extraction en dehors du worker existant.
_SONDE = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"xref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n"
    b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n110\n%%EOF\n"
)
_ATTENDU = {"ok": False, "code": "PDF_PAGES_BORNEES"}


def _refuser(message: str) -> int:
    print(f"not ready pdf: {message}", file=sys.stderr)
    return 1


def verifier_pdf() -> int:
    if sys.platform != "linux":
        return _refuser("Linux requis, isolation indisponible")
    try:
        # Même variable que le stockage réel. OPSYS_DATABASE_URL concerne la mémoire
        # d'entreprise ; elle ne suffit pas à déterminer le dialecte de cette base.
        url = os.environ.get(stockage.ENV_URL, "").strip()
        dialecte = make_url(url).get_backend_name() if url else "sqlite"
    except Exception:
        return _refuser("configuration du stockage invalide")
    if dialecte != "sqlite":
        return _refuser("backend non qualifié, SQLite requis")
    try:
        reference = fusion_csv._reference_cle()
        fusion_csv._aesgcm()
    except Exception:
        return _refuser("référence de clé ou chiffrement indisponible")
    try:
        attente = not fusion_csv._valeur_cle(reference)
    except Exception:
        return _refuser("fichier privé ou configuration de clé invalide")
    if not attente:
        try:
            fusion_csv._cle(reference)
        except Exception:
            return _refuser("clé externe invalide, 32 octets base64 requis")

    try:
        reponse = fusion_pdf._extraire_isole(_SONDE)
    except fusion_pdf.FusionPDFErreur as exc:
        code = exc.code if exc.code in fusion_pdf._TEMPORAIRES | fusion_pdf._REFUS else "PDF_VERIFICATION_ECHEC"
        return _refuser(f"isolation/worker indisponible ({code})")
    except Exception:
        return _refuser("isolation/worker indisponible")
    if not isinstance(reponse, dict) or type(reponse.get("ok")) is not bool or reponse != _ATTENDU:
        return _refuser("réponse de sonde worker inattendue, dépendances/isolation à vérifier")
    if attente:
        print("not ready pdf: clé externe absente dans la référence configurée", file=sys.stderr)
        return 3
    print("ready pdf: sonde isolée, parseur et clé externe vérifiés")
    return 0


class _ParseurPDF(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "not ready pdf: arguments invalides, voir --help\n")


def main(argv: list[str] | None = None) -> int:
    parseur = _ParseurPDF(description=__doc__)
    parseur.add_argument("--pdf-only", action="store_true", help="contrôle PDF seul pour le moteur natif")
    args = parseur.parse_args([] if argv is None else argv)
    if args.pdf_only:
        return verifier_pdf()
    try:
        rc_base = readiness.main()
    except Exception:
        return _refuser("readiness général indisponible")
    rc_pdf = verifier_pdf()
    # Une erreur runtime prime toujours sur une configuration opérateur absente.
    if rc_base not in (0, 3) or rc_pdf not in (0, 3):
        return 1
    return 3 if 3 in (rc_base, rc_pdf) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
