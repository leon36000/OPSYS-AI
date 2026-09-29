import { evaluerGarde } from "../roles/garde";
import { PROFILS } from "../roles/types";
import type { IdentiteOpsys, ResultatLectureIdentite } from "./contrat";
import {
  decider,
  identiteDepuisEtat,
  MOTIFS_ERREUR_IDENTITE,
  personneDepuisEtat,
  restaurerEtat,
  sessionDepuisEtat,
  type EtatIdentite,
} from "./etat";
import type { IdentiteMemorisee } from "./stockage";

const APPAREIL = "a".repeat(64);
const MAINTENANT = new Date("2026-09-29T14:30:00.000Z");

const EMPLOYE: IdentiteOpsys = { appareilId: APPAREIL, personne: "jdupont", role: "employee" };
const MEMORISEE: IdentiteMemorisee = { ...EMPLOYE, confirmeLe: "2026-09-28T08:00:00.000Z" };

describe("restaurerEtat — au démarrage, d'après le coffre", () => {
  test("aucune session -> non appairé", () => {
    expect(restaurerEtat(null, null)).toEqual({ genre: "non_appairee" });
    expect(restaurerEtat(null, MEMORISEE)).toEqual({ genre: "non_appairee" });
  });

  test("session sans identité gardée -> lecture en cours, aucun profil", () => {
    expect(restaurerEtat({ appareilId: APPAREIL }, null)).toEqual({ genre: "en_lecture" });
  });

  test("session avec identité gardée -> à reconfirmer, avec le moment de la dernière confirmation", () => {
    expect(restaurerEtat({ appareilId: APPAREIL }, MEMORISEE)).toEqual({
      genre: "a_reconfirmer",
      identite: EMPLOYE,
      confirmeLe: "2026-09-28T08:00:00.000Z",
    });
  });

  test("une identité gardée pour un AUTRE appareil ne sert pas", () => {
    expect(restaurerEtat({ appareilId: "b".repeat(64) }, MEMORISEE)).toEqual({ genre: "en_lecture" });
  });
});

describe("decider — après une lecture du serveur", () => {
  test("confirmée : le profil est celui du serveur, et il est gardé pour le hors ligne", () => {
    const resultat: ResultatLectureIdentite = { genre: "confirmee", identite: EMPLOYE };
    expect(decider(null, resultat, MAINTENANT)).toEqual({
      etat: { genre: "confirmee", identite: EMPLOYE },
      ecriture: { genre: "memoriser", identite: { ...EMPLOYE, confirmeLe: "2026-09-29T14:30:00.000Z" } },
    });
  });

  test("confirmée pour une AUTRE personne que la gardée : le serveur l'emporte, la garde est remplacée", () => {
    const autre: IdentiteOpsys = { appareilId: APPAREIL, personne: "mtremblay", role: "seller" };
    const decision = decider(MEMORISEE, { genre: "confirmee", identite: autre }, MAINTENANT);
    expect(decision.etat).toEqual({ genre: "confirmee", identite: autre });
    expect(decision.ecriture).toEqual({ genre: "memoriser", identite: { ...autre, confirmeLe: MAINTENANT.toISOString() } });
  });

  test.each(["appareil_non_attribue", "role_inconnu", "jeton_refuse", "refus_inattendu", "reponse_invalide"] as const)(
    "refusée (%s) : aucun profil, et l'identité gardée est effacée — un appareil refusé ne garde pas son profil",
    (motif) => {
      expect(decider(MEMORISEE, { genre: "refusee", motif }, MAINTENANT)).toEqual({
        etat: { genre: "erreur", motif },
        ecriture: { genre: "effacer" },
      });
      expect(decider(null, { genre: "refusee", motif }, MAINTENANT)).toEqual({
        etat: { genre: "erreur", motif },
        ecriture: { genre: "effacer" },
      });
    },
  );

  test("indisponible avec une identité gardée : elle sert, à reconfirmer, sans toucher au coffre", () => {
    expect(decider(MEMORISEE, { genre: "indisponible", message: "réseau" }, MAINTENANT)).toEqual({
      etat: { genre: "a_reconfirmer", identite: EMPLOYE, confirmeLe: "2026-09-28T08:00:00.000Z" },
      ecriture: null,
    });
  });

  test("indisponible SANS identité gardée : aucun profil, erreur (jamais un profil par défaut)", () => {
    expect(decider(null, { genre: "indisponible", message: "réseau" }, MAINTENANT)).toEqual({
      etat: { genre: "erreur", motif: "hors_ligne_sans_memoire" },
      ecriture: null,
    });
  });
});

describe("sessionDepuisEtat — la session que la garde de routes regarde", () => {
  test.each(["admin", "employee", "seller"] as const)("un rôle nommé confirmé (%s) ouvre le groupe de ce rôle, et lui seul", (role) => {
    const etat: EtatIdentite = { genre: "confirmee", identite: { appareilId: APPAREIL, personne: "p", role } };
    const session = sessionDepuisEtat(etat);
    expect(session).toEqual({ presente: true, role });
    for (const groupe of PROFILS) {
      expect(evaluerGarde(session, groupe).autorise).toBe(groupe === role);
    }
  });

  test("une identité à reconfirmer ouvre le profil gardé (hors ligne)", () => {
    const session = sessionDepuisEtat({ genre: "a_reconfirmer", identite: EMPLOYE, confirmeLe: MEMORISEE.confirmeLe });
    expect(session).toEqual({ presente: true, role: "employee" });
    expect(evaluerGarde(session, "employee").autorise).toBe(true);
  });

  const SANS_IDENTITE: readonly EtatIdentite[] = [
    { genre: "restauration" },
    { genre: "non_appairee" },
    { genre: "en_lecture" },
    ...MOTIFS_ERREUR_IDENTITE.map((motif): EtatIdentite => ({ genre: "erreur", motif })),
  ];

  test.each(SANS_IDENTITE.map((etat) => [etat.genre === "erreur" ? `erreur:${etat.motif}` : etat.genre, etat] as const))(
    "sans identité (%s) : aucune session, aucun groupe ouvert — jamais un profil par défaut",
    (_nom, etat) => {
      const session = sessionDepuisEtat(etat);
      expect(session).toEqual({ presente: false });
      for (const groupe of PROFILS) {
        expect(evaluerGarde(session, groupe).autorise).toBe(false);
      }
      expect(identiteDepuisEtat(etat)).toBeNull();
      expect(personneDepuisEtat(etat)).toBeNull();
    },
  );

  test("le rôle de transport « operator » n'ouvre aucun groupe, même s'il arrivait jusque-là", () => {
    expect(evaluerGarde({ presente: true, role: "operator" }, "employee").autorise).toBe(false);
  });
});

describe("personneDepuisEtat", () => {
  test("la personne du serveur, confirmée ou à reconfirmer", () => {
    expect(personneDepuisEtat({ genre: "confirmee", identite: EMPLOYE })).toBe("jdupont");
    expect(personneDepuisEtat({ genre: "a_reconfirmer", identite: EMPLOYE, confirmeLe: MEMORISEE.confirmeLe })).toBe("jdupont");
  });
});

describe("MOTIFS_ERREUR_IDENTITE", () => {
  test("liste les refus du serveur et les deux échecs que seule l'app voit", () => {
    expect([...MOTIFS_ERREUR_IDENTITE].sort()).toEqual(
      [
        "appareil_non_attribue",
        "hors_ligne_sans_memoire",
        "jeton_refuse",
        "refus_inattendu",
        "reponse_invalide",
        "role_inconnu",
        "stockage_illisible",
      ].sort(),
    );
  });
});
