import { creerChargeurDevis } from "../vendeur/chargeurDevis";
import {
  capturerSessionLecture,
  definirConfigurationAppel,
  definirPersonneConfirmee,
} from "../protocole/configuration";
import type { ResultatAppelOutil } from "../protocole/client";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { config, enveloppeCouple, transportHorsLigne } from "../admin/donneesDeTest";
import { interpreter } from "../admin/enveloppe";
import { lireSection } from "../admin/lecture";
import { ecrireCacheSection, lireCacheSection } from "../admin/cache";
import { ecrireProprietaireDesCaches, synchroniserCaches } from "./caches";
import type { EtatIdentite } from "./etat";

function differer<T>() {
  let resoudre!: (value: T) => void;
  const promesse = new Promise<T>((resolve) => {
    resoudre = resolve;
  });
  return { promesse, resoudre };
}

const SECTION = {
  outil: "m5_etat_tresorerie",
  args: {},
  cache: "lecture-en-vol-fictive",
  interpreter: (raw: unknown) =>
    interpreter(raw, "couple", (value) =>
      typeof (value as { n?: unknown }).n === "number" ? (value as { n: number }) : null,
    ),
};
const CONFIRMEE_B: EtatIdentite = {
  genre: "confirmee",
  identite: { appareilId: "appareil-fictif", personne: "employe-fictif-b", role: "employee" },
};
const ROLE_RETIRE: EtatIdentite = {
  genre: "confirmee",
  identite: { appareilId: "appareil-fictif", personne: "nathan", role: "employee" },
};
const REVOQUEE: EtatIdentite = { genre: "erreur", motif: "jeton_refuse" };

test.each([CONFIRMEE_B, ROLE_RETIRE, REVOQUEE])(
  "une réponse admin tardive ne repeuple pas le cache après $genre",
  async (etat) => {
    const depot = new DepotCleValeurMemoire();
    await ecrireProprietaireDesCaches(depot, { personne: "nathan", role: "admin" });
    const started = differer<void>();
    const reply = differer<ResultatAppelOutil>();
    const transport = jest.fn(async () => {
      started.resoudre();
      return reply.promesse;
    });
    const pending = lireSection(config(transport, { depot }), SECTION);
    await started.promesse;
    await synchroniserCaches(depot, etat);
    reply.resoudre({ ok: true, result: enveloppeCouple({ n: 777 }) });
    const result = await pending;
    expect(await lireCacheSection(depot, "nathan", SECTION.cache)).toBeNull();
    expect(result.source).toBe("aucune");
  },
);

test("une copie cache déjà lue mais rendue après purge est écartée", async () => {
  const started = differer<void>();
  const release = differer<void>();
  class DepotLectureRetardee extends DepotCleValeurMemoire {
    async lire(cle: string) {
      const value = await super.lire(cle);
      if (cle.startsWith("admin:")) {
        started.resoudre();
        await release.promesse;
      }
      return value;
    }
  }
  const depot = new DepotLectureRetardee();
  await ecrireProprietaireDesCaches(depot, { personne: "nathan", role: "admin" });
  await ecrireCacheSection(
    depot,
    "nathan",
    SECTION.cache,
    enveloppeCouple({ n: 777 }),
    "2026-10-06T18:00:00Z",
  );
  const pending = lireSection(config(transportHorsLigne(), { depot }), SECTION);
  await started.promesse;
  await synchroniserCaches(depot, CONFIRMEE_B);
  release.resoudre();
  expect((await pending).source).toBe("aucune");
});

test("la purge termine après une écriture déjà engagée et écarte son retour", async () => {
  const started = differer<void>();
  const release = differer<void>();
  class DepotEcritureRetardee extends DepotCleValeurMemoire {
    async ecrire(cle: string, value: string) {
      if (cle.startsWith("admin:")) {
        started.resoudre();
        await release.promesse;
      }
      await super.ecrire(cle, value);
    }
  }
  const depot = new DepotEcritureRetardee();
  await ecrireProprietaireDesCaches(depot, { personne: "nathan", role: "admin" });
  const transport = jest.fn(async () => ({
    ok: true as const,
    result: enveloppeCouple({ n: 777 }),
  }));
  const pending = lireSection(config(transport, { depot }), SECTION);
  await started.promesse;
  const purge = synchroniserCaches(depot, CONFIRMEE_B);
  // Release via a semantic gate, without timers or sleeps. The purge must order
  // its deletion after this pending write, regardless of promise scheduling.
  release.resoudre();
  const [result] = await Promise.all([pending, purge]);
  expect(await lireCacheSection(depot, "nathan", SECTION.cache)).toBeNull();
  expect(result.source).toBe("aucune");
});

test("une purge échouée est retentée à la confirmation de la même identité", async () => {
  class DepotPurgeFragile extends DepotCleValeurMemoire {
    echouer = false;
    async supprimerParPrefixe(prefixe: string) {
      if (this.echouer) throw new Error("purge fictive interrompue");
      await super.supprimerParPrefixe(prefixe);
    }
  }
  const depot = new DepotPurgeFragile();
  await ecrireProprietaireDesCaches(depot, { personne: "nathan", role: "admin" });
  await ecrireCacheSection(
    depot,
    "nathan",
    SECTION.cache,
    enveloppeCouple({ n: 777 }),
    "2026-10-06T18:00:00Z",
  );
  depot.echouer = true;
  await expect(synchroniserCaches(depot, REVOQUEE)).rejects.toThrow("interrompue");
  expect((await lireSection(config(transportHorsLigne(), { depot }), SECTION)).source).toBe(
    "aucune",
  );
  const memeIdentite: EtatIdentite = {
    genre: "confirmee",
    identite: { appareilId: "appareil-fictif", personne: "nathan", role: "admin" },
  };
  await expect(synchroniserCaches(depot, memeIdentite)).rejects.toThrow("interrompue");
  expect((await lireSection(config(transportHorsLigne(), { depot }), SECTION)).source).toBe(
    "aucune",
  );
  depot.echouer = false;
  expect((await synchroniserCaches(depot, memeIdentite)).genre).toBe("purger_puis_marquer");
  expect(await lireCacheSection(depot, "nathan", SECTION.cache)).toBeNull();
  await ecrireCacheSection(
    depot,
    "nathan",
    SECTION.cache,
    enveloppeCouple({ n: 888 }),
    "2026-10-06T19:00:00Z",
  );
  const relue = await lireSection(config(transportHorsLigne(), { depot }), SECTION);
  expect(relue.source).toBe("cache");
  if (relue.source === "cache") expect(relue.valeur.n).toBe(888);
});

test("un ancien chargeur de devis indique les deux sources indisponibles après purge", async () => {
  const depot = new DepotCleValeurMemoire();
  const appelerOutil = jest.fn();
  const chargeur = creerChargeurDevis(config(appelerOutil, { depot }));
  await synchroniserCaches(depot, CONFIRMEE_B);
  const resultat = await chargeur.chargerDevis();
  expect(resultat.entrees).toEqual([]);
  expect(resultat.sources).toEqual(
    ["won_pending_schedule", "quote_stale"].map((segment) => ({
      segment,
      etat: {
        genre: "echouee",
        refuse: false,
        verdict: expect.objectContaining({ code: "lecture_remplacee" }),
      },
    })),
  );
  expect(appelerOutil).not.toHaveBeenCalled();
});

test("la capture avant acquisition du dépôt survit à une confirmation identique, mais pas au retrait du rôle", () => {
  const configuration = {
    urlBase: "https://passerelle.fictif.test",
    jeton: "jeton-fictif",
    appareilId: "appareil-fictif",
  };
  const personne = {
    jeton: configuration.jeton,
    appareilId: configuration.appareilId,
    personne: "nathan",
    role: "admin",
  };
  try {
    definirConfigurationAppel(configuration);
    definirPersonneConfirmee(personne);
    const capture = capturerSessionLecture();
    definirPersonneConfirmee({ ...personne });
    expect(capture.courante()).toBe(true);
    definirPersonneConfirmee({ ...personne, role: "employee" });
    expect(capture.courante()).toBe(false);
    definirPersonneConfirmee(personne);
    expect(capture.courante()).toBe(false);
  } finally {
    definirPersonneConfirmee(null);
    definirConfigurationAppel(null);
  }
});
