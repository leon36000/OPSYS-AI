import { evaluerGarde } from "./garde";
import { PROFILS, type Profil, type SessionAppareil } from "./types";

describe("evaluerGarde", () => {
  describe("session absente", () => {
    test.each(PROFILS)("refuse le groupe %s et redirige vers /pairing", (groupe) => {
      const verdict = evaluerGarde({ presente: false }, groupe);
      expect(verdict).toEqual({
        autorise: false,
        motif: "session_absente",
        redirectionVers: "/pairing",
      });
    });
  });

  describe("matrice exhaustive rôle connu × groupe visé", () => {
    for (const role of PROFILS) {
      for (const groupe of PROFILS) {
        const session: SessionAppareil = { presente: true, role };
        const attendu = role === groupe;
        test(`role=${role} groupe=${groupe} -> autorise=${attendu}`, () => {
          const verdict = evaluerGarde(session, groupe);
          if (attendu) {
            expect(verdict).toEqual({ autorise: true });
          } else {
            expect(verdict).toEqual({
              autorise: false,
              motif: "role_non_autorise",
              redirectionVers: "/pairing",
            });
          }
        });
      }
    }

    // Le cas nommé explicitement par la mission : un jeton employé n'atteint jamais (admin).
    test("un jeton employee est refusé pour le groupe admin, même en URL directe", () => {
      const verdict = evaluerGarde({ presente: true, role: "employee" }, "admin");
      expect(verdict.autorise).toBe(false);
    });
  });

  describe("rôle inconnu — fail-closed", () => {
    const rolesInconnus = ["proprietaire", "", "ADMIN", "admin ", " employee", "root", "owner", "system_agent"];

    test.each(rolesInconnus)("le rôle %j est refusé pour chaque groupe", (role) => {
      for (const groupe of PROFILS) {
        const verdict = evaluerGarde({ presente: true, role }, groupe);
        expect(verdict).toEqual({
          autorise: false,
          motif: "role_inconnu",
          redirectionVers: "/pairing",
        });
      }
    });
  });

  test("ne modifie jamais les objets reçus (pureté)", () => {
    const session: SessionAppareil = { presente: true, role: "admin" };
    const copie = { ...session };
    evaluerGarde(session, "employee");
    expect(session).toEqual(copie);
  });

  test("est déterministe : deux appels identiques donnent le même verdict", () => {
    const session: SessionAppareil = { presente: true, role: "seller" };
    expect(evaluerGarde(session, "seller")).toEqual(evaluerGarde(session, "seller"));
  });
});

// Couvre explicitement les 4 profils connus + les rôles inconnus ci-dessus : chaque rôle ×
// chaque groupe (16 combinaisons connues + 8 rôles inconnus × 4 groupes) et la session absente
// (4 groupes) — la matrice exhaustive demandée par PLAN T1.4-a, item 3.
test("PROFILS contient exactement les 4 profils attendus", () => {
  const attendu: Profil[] = ["admin", "employee", "seller", "client"];
  expect([...PROFILS].sort()).toEqual([...attendu].sort());
});
