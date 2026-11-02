"""Révocation humaine interactive d'une liaison de session M10.

Usage : ``python -m opsys.memoire_liaison --session <clé> --ligne <ligne_id> --motif <texte>``.
L'identifiant de la personne ne peut pas venir des arguments de commande : il est demandé en
interactif puis son mot de passe est vérifié dans la base avant le CAS append-only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import sys

from . import etat, identite, stockage
from .stockage.concurrence import relire_si_conflit, verrou_ecriture_console
from .stockage.portabilite import DIALECTES_QUALIFIES

ROLES_AUTORISES = frozenset({"admin", "nathan_owner"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m opsys.memoire_liaison")
    parser.add_argument("--session", required=True, help="clé de session privée à révoquer")
    parser.add_argument("--ligne", required=True, help="ligne active attendue (CAS)")
    parser.add_argument("--motif", required=True, help="motif de révocation, 10 à 500 caractères")
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("authentification personnelle interactive requise; aucune modification effectuée", file=sys.stderr)
        return 1
    identifiant = input("Identifiant de la personne : ").strip()
    try:
        mot_de_passe = getpass.getpass("Mot de passe : ")
    except (EOFError, OSError):
        mot_de_passe = ""
    with etat.session() as cnx:
        personne = identite.authentifier(cnx, identifiant, mot_de_passe)
        if personne is None or not personne.roles.intersection(ROLES_AUTORISES):
            print("authentification personnelle requise; aucune modification effectuée", file=sys.stderr)
            return 1
        from m10_memoire import humain, liaison, registre

        if cnx.dialect.name not in DIALECTES_QUALIFIES:
            print("révocation indisponible hors de SQLite et PostgreSQL", file=sys.stderr)
            return 1
        # PostgreSQL : un seul écrivain humain à la fois, et le perdant d'une course sur le registre est REJOUÉ
        # (il relit la liaison du gagnant : « liaison modifiée ou absente ») ; sous SQLite, rien ne change.
        verrou_ecriture_console(cnx)

        def revoquer() -> tuple[int, str, dict | None]:
            reg = registre.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
            try:
                actif = liaison.liaison_courante(args.session, reg)
            except ValueError:
                actif = None
            if actif is None or actif.get("ligne_id") != args.ligne:
                return 1, "liaison modifiée ou absente; relire avant de révoquer", None
            role = sorted(personne.roles.intersection(ROLES_AUTORISES))[0]
            resultat, refus = liaison.revoquer_session_affaire(
                args.session,
                args.ligne,
                personne.identifiant,
                role,
                humain.SOURCE_CLI,
                args.motif,
                dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                reg,
            )
            if refus is not None:
                return 1, f"révocation refusée: {refus['code']}: {refus['detail']}", None
            return 0, "", resultat

        code, message, resultat = relire_si_conflit(revoquer)
        if code != 0:
            print(message, file=sys.stderr)
            return 1
    print(f"liaison révoquée; ligne d'audit {resultat['ligne_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
