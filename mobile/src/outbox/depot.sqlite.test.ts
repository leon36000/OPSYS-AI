// `expo-sqlite` est natif : absent de Jest. Ce test fait tourner le VRAI SQL de `depot.sqlite.ts` sur un
// moteur SQLite réel (`node:sqlite`, Node 22.5+, celui de la CI mobile) derrière la petite interface
// qu'`expo-sqlite` expose et que l'adaptateur utilise (`execAsync`, `getAllAsync`, `getFirstAsync`,
// `runAsync`). Il prouve le SQL et la migration ; il ne prouve PAS le pont natif d'`expo-sqlite`.
import { DatabaseSync } from "node:sqlite";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type { SQLiteDatabase } from "expo-sqlite";

import { creerDepotOutboxSqlite, DDL_OUTBOX, initialiserSchemaOutbox } from "./depot.sqlite";
import { capturerMutationOutbox, DepotOutboxMemoire } from "./depot";
import { creerMutation, marquerEnvoi, soumettreMutation } from "./mutation";
import { avecProprietaire } from "./proprietaire";
import { creerVidangeur } from "./vidangeur";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { invoquerOutil } from "../protocole/client";
import type { MutationOutbox } from "./types";
import type { LigneContenuM7 } from "../m7/contrat";
import { creerMutationDecisionMarketing } from "../m7/decisionOutbox";
import { calculerEtatEnvoiFichier } from "../fichiers/etatEnvoi";

type Parametres = (string | number | null)[];

function baseReelle(fichier = ":memory:"): { base: SQLiteDatabase; brute: DatabaseSync } {
  const brute = new DatabaseSync(fichier);
  const base = {
    async execAsync(sql: string): Promise<void> {
      brute.exec(sql);
    },
    async getAllAsync<T>(sql: string, parametres: Parametres = []): Promise<T[]> {
      return brute.prepare(sql).all(...parametres) as T[];
    },
    async getFirstAsync<T>(sql: string, parametres: Parametres = []): Promise<T | null> {
      return (brute.prepare(sql).get(...parametres) as T | undefined) ?? null;
    },
    async runAsync(sql: string, parametres: Parametres = []): Promise<void> {
      brute.prepare(sql).run(...parametres);
    },
  };
  return { base: base as unknown as SQLiteDatabase, brute };
}

const HORLOGE = { maintenant: new Date("2026-09-29T12:00:00.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `id-${++compteur}`;

beforeEach(() => {
  compteur = 0;
});

function nouvelleMutation() {
  return creerMutation({ type: "punch_in", chantierId: "interv-1", payload: { action: "arrivee" } }, idDeterministe, HORLOGE);
}

function colonnes(brute: DatabaseSync): string[] {
  return (brute.prepare("PRAGMA table_info(outbox)").all() as { name: string }[]).map((c) => c.name);
}

/** La table telle qu'elle existait AVANT PLAN T1.4-l : sans `proprietaire`. */
const DDL_AVANT_T1_4_L = DDL_OUTBOX.replace(",\n  proprietaire TEXT,\n  resume_accepte TEXT,\n  destination TEXT", "");

describe("initialiserSchemaOutbox : la colonne proprietaire", () => {
  test("base neuve : la table naît avec la colonne proprietaire", async () => {
    const { base, brute } = baseReelle();
    await initialiserSchemaOutbox(base);
    expect(colonnes(brute)).toContain("proprietaire");
  });

  test("le gabarit d'avant T1.4-l n'a bien PAS la colonne (le test de migration teste ce qu'il croit tester)", () => {
    const { brute } = baseReelle();
    brute.exec(DDL_AVANT_T1_4_L);
    expect(colonnes(brute)).not.toContain("proprietaire");
  });

  test("base d'avant T1.4-l : la colonne est ajoutée, les lignes existantes sont gardées, propriétaire NULL", async () => {
    const { base, brute } = baseReelle();
    brute.exec(DDL_AVANT_T1_4_L);
    brute
      .prepare(
        `INSERT INTO outbox (id, sequence, type, chantier_id, payload, depends_on, statut, tentatives, created_at_local, prochaine_tentative_a)
         VALUES ('vieille', 1, 'punch_in', 'interv-1', '{"action":"arrivee"}', NULL, 'en_attente', 2, '2026-09-01T08:00:00-04:00', NULL)`,
      )
      .run();

    await initialiserSchemaOutbox(base);

    expect(colonnes(brute)).toContain("proprietaire");
    const lignes = await creerDepotOutboxSqlite(base).lister();
    expect(lignes).toHaveLength(1);
    expect(lignes[0]).toMatchObject({ id: "vieille", statut: "en_attente", tentatives: 2, proprietaire: null });
  });

  test("idempotent : un second démarrage ne casse rien et n'ajoute pas la colonne deux fois", async () => {
    const { base, brute } = baseReelle();
    brute.exec(DDL_AVANT_T1_4_L);
    await initialiserSchemaOutbox(base);
    await initialiserSchemaOutbox(base);
    expect(colonnes(brute).filter((nom) => nom === "proprietaire")).toHaveLength(1);
  });
});

describe("creerDepotOutboxSqlite : le propriétaire de chaque mutation", () => {
  test("les accusés de reprise par indices restent durables et séparés par propriétaire", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);
    // État serveur FICTIF, conservé comme historique local avec son contexte lié. Pas un pret live.
    const SHA = "f".repeat(64);
    const contexte = { empreinte_sha256: SHA, taille_octets: 262145, type_mime: "image/png", nombre_blocs: 2 };
    const creerRecu = (id: string, index: number, proprietaire: string) => ({
      ...creerMutation({ type: "fichier_bloc_reconcilie", chantierId: "I1", payload: { ...contexte, index_bloc: index } }, () => id, HORLOGE),
      statut: "envoyee" as const, proprietaire,
      resumeAccepte: { genre: "etat_fichier", contexte,
        etat: { existe: true, complet: index === 1, blocsRecus: index === 1 ? [0, 1] : [0], reference: index === 1 ? `fichier:sha256:${SHA}` : null } },
    });
    await depot.inserer(creerRecu("a0", 0, "jdupont"));
    await depot.inserer(creerRecu("b1", 1, "mtremblay"));
    const relues = await depot.lister();
    const a = relues.filter((m) => m.proprietaire === "jdupont");
    expect(a).toHaveLength(1);
    expect(a[0].resumeAccepte).toEqual({ genre: "etat_fichier", contexte,
      etat: { existe: true, complet: false, blocsRecus: [0], reference: null } });
    expect(calculerEtatEnvoiFichier(a, "I1", SHA)).toMatchObject({ statut: "en_cours", blocsEnvoyes: 1, nombreBlocs: 2 });
    await depot.inserer(creerRecu("a1", 1, "jdupont"));
    expect(calculerEtatEnvoiFichier((await depot.lister()).filter((m) => m.proprietaire === "jdupont"), "I1", SHA))
      .toMatchObject({ statut: "complet", blocsEnvoyes: 2, nombreBlocs: 2 });
  });

  test("legacy reconcilie illisible reste durable sans être promu en fichier complet", async()=>{
    const {base}=baseReelle();await initialiserSchemaOutbox(base);const depot=creerDepotOutboxSqlite(base);
    const legacy={...creerMutation({type:"fichier_bloc_reconcilie",chantierId:"I-LEGACY-FICTIF",payload:{empreinte_sha256:"f".repeat(64),index_bloc:0,nombre_blocs:1}},()=>"LEGACY-FICTIF",HORLOGE),statut:"envoyee" as const,proprietaire:"jdupont",resumeAccepte:{existe:true,complet:true,blocsRecus:[0],reference:"fichier:sha256:"+"f".repeat(64)}};
    await depot.inserer(legacy);const relue=await depot.obtenir(legacy.id);
    expect(relue).toMatchObject({id:legacy.id,payload:legacy.payload,resumeAccepte:legacy.resumeAccepte,statut:"envoyee"});
    expect(calculerEtatEnvoiFichier(await depot.lister(),"I-LEGACY-FICTIF","f".repeat(64))).toMatchObject({statut:"en_cours",reference:null,blocsEnvoyes:0});
  });

  test("inserer écrit le propriétaire, lister et obtenir le relisent, avec la sequence assignée par la base", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);

    const persistee = await depot.inserer({ ...nouvelleMutation(), proprietaire: "jdupont", resumeAccepte: { wct_id: "W1" } });

    expect(persistee.sequence).toBe(1);
    expect(persistee.proprietaire).toBe("jdupont");
    expect((await depot.obtenir(persistee.id))?.resumeAccepte).toEqual({ wct_id: "W1" });
    expect((await depot.obtenir(persistee.id))?.proprietaire).toBe("jdupont");
    expect((await depot.lister())[0]).toEqual(persistee);
  });

  test("une mutation sans propriétaire est écrite avec NULL et relue null (jamais une chaîne vide ou un défaut)", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);

    const persistee = await depot.inserer(nouvelleMutation());

    expect(persistee.proprietaire).toBeNull();
    expect((await depot.obtenir(persistee.id))?.proprietaire).toBeNull();
  });

  test("mettreAJour change le statut mais jamais le propriétaire (même si la mutation passée en porte un autre)", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);
    const persistee = await depot.inserer({ ...nouvelleMutation(), proprietaire: "jdupont" });

    const enEnvoi = marquerEnvoi(soumettreMutation(persistee));
    await depot.mettreAJour({ ...enEnvoi, proprietaire: "mtremblay" });

    const relue = await depot.obtenir(persistee.id);
    expect(relue?.statut).toBe("envoi");
    expect(relue?.proprietaire).toBe("jdupont");
  });

  test("avec le dépôt de l'app (avecProprietaire) : la personne courante est posée à l'insertion, en base", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = avecProprietaire(creerDepotOutboxSqlite(base), () => "mtremblay");

    const persistee = await depot.inserer(nouvelleMutation());

    expect(persistee.proprietaire).toBe("mtremblay");
    expect((await creerDepotOutboxSqlite(base).obtenir(persistee.id))?.proprietaire).toBe("mtremblay");
  });

  test("la sequence croît d'une insertion à l'autre, quel que soit le propriétaire", async () => {
    const { base } = baseReelle();
    await initialiserSchemaOutbox(base);
    const depot = creerDepotOutboxSqlite(base);

    const a = await depot.inserer({ ...nouvelleMutation(), proprietaire: "jdupont" });
    const b = await depot.inserer({ ...nouvelleMutation(), proprietaire: "mtremblay" });

    expect([a.sequence, b.sequence]).toEqual([1, 2]);
  });
});


describe("CF037 — CAS natif mémoire/SQLite et propriétaire", () => {
  test.each(["memoire", "sqlite"])("%s refuse snapshot périmé et toute réécriture d'intention", async moteur => {
    const { base, brute } = baseReelle();
    try {
      await initialiserSchemaOutbox(base);
      const depot = avecProprietaire(moteur === "sqlite" ? creerDepotOutboxSqlite(base) : new DepotOutboxMemoire(), () => "jdupont");
      const originale = await depot.inserer(soumettreMutation(nouvelleMutation()));
      const attendue = capturerMutationOutbox(originale);
      const envoi = marquerEnvoi(originale);
      expect(await depot.mettreAJourSiInchangee(attendue, envoi)).toBe(true);
      const avantRecu = capturerMutationOutbox(envoi);
      const terminale = { ...envoi, statut: "envoyee" as const, resumeAccepte: { confirmation: "RECU-FICTIF" } };
      await depot.mettreAJour(terminale);
      expect(await depot.mettreAJourSiInchangee(avantRecu, { ...envoi, statut: "echec_permanent" })).toBe(false);
      expect(await depot.obtenir(originale.id)).toEqual(terminale);
      const actuel = capturerMutationOutbox(terminale);
      for (const autre of [ { ...terminale, payload: { action: "autre" } }, { ...terminale, proprietaire: "autre" },
        { ...terminale, createdAtLocal: "autre-heure" }, { ...terminale, id: "autre-id" } ]) {
        expect(await depot.mettreAJourSiInchangee(actuel, autre)).toBe(false);
        expect(await depot.obtenir(originale.id)).toEqual(terminale);
      }
      // Même statut et même clé ne suffisent pas si la charge actuelle a changé.
      const remplacee = { ...terminale, payload: { action: "corrigee" } };
      await depot.mettreAJour(remplacee);
      expect(await depot.mettreAJourSiInchangee(actuel, terminale)).toBe(false);
      expect(await depot.obtenir(originale.id)).toEqual(remplacee);
    } finally { brute.close(); }
  });

  test("SQLite compare dans l'UPDATE même si un reçu arrive juste avant son exécution", async () => {
    const { base, brute } = baseReelle();
    try {
      await initialiserSchemaOutbox(base);
      const depot = creerDepotOutboxSqlite(base);
      const originale = await depot.inserer({ ...soumettreMutation(nouvelleMutation()), proprietaire: "jdupont" });
      const attendue = capturerMutationOutbox(originale);
      const sqlExecuter = base.getFirstAsync.bind(base);
      const instructions: string[] = [];
      const espion = jest.spyOn(base, "getFirstAsync").mockImplementation(async (sql, params) => {
        instructions.push(sql);
        if (sql.startsWith("UPDATE")) {
          brute.prepare("UPDATE outbox SET statut='envoyee', resume_accepte=? WHERE id=?").run('{"confirmation":"CONCURRENT-FICTIF"}', originale.id);
        }
        return sqlExecuter(sql, params);
      });
      expect(await depot.mettreAJourSiInchangee(attendue, marquerEnvoi(originale))).toBe(false);
      expect(instructions).toHaveLength(1);
      expect(instructions[0]).toMatch(/^UPDATE/);
      espion.mockRestore();
      expect(await depot.obtenir(originale.id)).toMatchObject({ statut: "envoyee", resumeAccepte: { confirmation: "CONCURRENT-FICTIF" } });
    } finally { brute.close(); }
  });
});

// Par défaut, la CI ferme/réouvre une base fichier dans ce processus. La qualification externe peut
// exécuter prepare puis resume dans DEUX processus Jest, sur le même fichier neuf conservé en preuve.
// Transport/ACK fictifs : ni effet serveur réel, ni pont Expo, ni panne électrique ne sont prouvés.
test("CF037 — reprise fichier d'une intention inconnue, quarantaine et série durable", async () => {
  const phase = process.env.CF037_PHASE;
  if (phase !== undefined && phase !== "prepare" && phase !== "resume") throw new Error("phase CF037 invalide");
  const externe = process.env.CF037_SQLITE_PATH;
  if ((phase === undefined) !== (externe === undefined)) throw new Error("phase et fichier CF037 doivent être fournis ensemble");
  const dossier = externe ? null : mkdtempSync(join(tmpdir(), "opsys-cf037-"));
  const fichier = externe ?? join(dossier!, "outbox.sqlite");
  const preuve = `${fichier}.attendu.json`;
  const personne = "admin.fictif";
  const sessionInitiale = { urlBase: "https://passerelle.fictif.invalid", jeton: "jeton-fictif-a", appareilId: "appareil-fictif-a", personne };
  const idA = "00000000-0000-4000-8000-000000000001";
  const idSuivant = "00000000-0000-4000-8000-000000000002";
  const idB = "00000000-0000-4000-8000-000000000003";
  const contenuA = "10000000-0000-4000-8000-000000000001";
  const contenuB = "10000000-0000-4000-8000-000000000002";
  const item = (contenu_id: string): LigneContenuM7 => ({ contenu_id, wct_id: "a".repeat(64),
    plateforme: "demande_temoignage", revision: 1, approval_status: "PROPOSE", exporte: false,
    marque_source: null, fraicheur_marque: "preuve_absente", texte: "Texte fictif CF037", origine_texte: "gabarit",
    mots_clics: [], lien_utm: null, avertissements: [], decision: null,
    consentement: { recueilli_par: personne, recueilli_le: "2026-09-29T11:00:00Z", version_texte: "fictif" } });
  const ack = (id: string, par = personne) => ({ contenu_id: id === idB ? contenuB : contenuA,
    plateforme: "demande_temoignage", approval_status: id === idSuivant ? "REJECTED" : "APPROVED", par,
    source: "appareil", horodatage: "2026-09-29T12:00:00Z", empreinte_texte: "b".repeat(64),
    prochaine_etape: "Paquet manuel fictif, aucune publication" });
  const reponse = (id: string, par = personne) => new Response(JSON.stringify({ ok: true,
    result: { ok: true, resultat: { accepte: true, resultat: ack(id, par) } } }), { status: 200 });
  const originale = (id: string) => creerMutationDecisionMarketing(item(id === idB ? contenuB : contenuA),
    id === idSuivant ? "rejeter" : "approuver", "Motif fictif explicite", () => id, HORLOGE);
  // Oracle RPC indépendant de la projection du descripteur : aucune preuve locale ne fuit dans args.
  const requete = (id: string) => ({ tool: "m7_decider_contenu", idempotencyKey: id,
    deviceId: sessionInitiale.appareilId, deviceTimestamp: "2026-09-29T08:00:00-04:00",
    args: { contenu_id: id === idB ? contenuB : contenuA, decision: id === idSuivant ? "rejeter" : "approuver",
      horodatage: "2026-09-29T08:00:00-04:00", ...(id === idSuivant ? { motif: "Motif fictif explicite" } : {}) } });
  try {
    if (phase !== "resume") {
      expect(existsSync(fichier)).toBe(false);
      const { base, brute } = baseReelle(fichier);
      try {
        await initialiserSchemaOutbox(base);
        const depot = avecProprietaire(creerDepotOutboxSqlite(base), () => personne, () => sessionInitiale.urlBase);
        for (const id of [idA, idSuivant, idB]) await depot.inserer(originale(id));
        const appels: unknown[] = [];
        const fetchFictif: typeof fetch = async (url, init) => {
          expect(url).toBe(`${sessionInitiale.urlBase}/tools/invoke`);
          expect(init?.headers).toEqual({ "content-type": "application/json", authorization: `Bearer ${sessionInitiale.jeton}` });
          const corps = JSON.parse(String(init?.body)); appels.push(corps);
          if (corps.idempotencyKey === idA) throw new Error("ACK perdu FICTIF : issue serveur inconnue");
          expect(corps).toEqual(requete(idB)); return reponse(idB);
        };
        const rapport = await creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
          fetchImpl: fetchFictif, session: () => sessionInitiale, maintenant: () => HORLOGE.maintenant }).vidangerFileSortante();
        expect(appels).toEqual([requete(idA), requete(idB)]);
        expect(rapport).toMatchObject({ envoyees: [idB], remisesEnAttente: [idA], bloquees: [idSuivant], echecsPermanents: [], quarantaine: [], arret: null });
        const lignes = await depot.lister();
        expect(await depot.obtenir(idA)).toMatchObject({ ...originale(idA), proprietaire: personne, sequence: 1, tentatives: 1, prochaineTentativeA: "2026-09-29T12:00:01.000Z" });
        expect((await depot.obtenir(idA))?.prochaineTentativeA).not.toBeNull();
        expect(await depot.obtenir(idSuivant)).toMatchObject({ sequence: 2, statut: "en_attente", tentatives: 0 });
        expect(await depot.obtenir(idB)).toMatchObject({ sequence: 3, statut: "envoyee", resumeAccepte: ack(idB) });
        writeFileSync(preuve, JSON.stringify({ fictif: true, pid: process.pid, lignes }), { flag: "wx" });
      } finally { brute.close(); }
    }
    if (phase !== "prepare") {
      const attendu: { fictif: boolean; pid: number; lignes: MutationOutbox[] } = JSON.parse(readFileSync(preuve, "utf8"));
      expect(attendu.fictif).toBe(true);
      if (phase === "resume") expect(process.pid).not.toBe(attendu.pid);
      const { base, brute } = baseReelle(fichier);
      let terminales: MutationOutbox[];
      try {
        await initialiserSchemaOutbox(base);
        const depot = creerDepotOutboxSqlite(base);
        expect(await depot.lister()).toEqual(attendu.lignes);
        const avant = capturerMutationOutbox((await depot.obtenir(idA))!);
        let session = { ...sessionInitiale, personne: "autre.fictif", jeton: "jeton-fictif-autre" };
        let maintenant = HORLOGE.maintenant;
        let mauvaisRecu = true;
        const appels: unknown[] = [];
        const fetchFictif: typeof fetch = async (url, init) => {
          expect(url).toBe(`${sessionInitiale.urlBase}/tools/invoke`);
          expect(init?.headers).toEqual({ "content-type": "application/json", authorization: "Bearer jeton-fictif-renouvele" });
          const corps = JSON.parse(String(init?.body)); appels.push(corps);
          expect([idA, idSuivant]).toContain(corps.idempotencyKey);
          expect(corps).toEqual(requete(corps.idempotencyKey));
          return reponse(corps.idempotencyKey, mauvaisRecu ? "autre.fictif" : personne);
        };
        const vidangeur = creerVidangeur({ depot, descripteurs: DESCRIPTEURS_MUTATION, appelerOutil: invoquerOutil,
          fetchImpl: fetchFictif, session: () => session, maintenant: () => maintenant });
        const quarantaine = await vidangeur.vidangerFileSortante();
        expect(quarantaine.quarantaine).toEqual([idA, idSuivant]);
        expect(appels).toEqual([]); expect(await depot.lister()).toEqual(attendu.lignes);
        session = { ...sessionInitiale, jeton: "jeton-fictif-renouvele" };
        expect((await vidangeur.vidangerFileSortante()).bloquees).toContain(idSuivant);
        expect(appels).toEqual([]); expect(await depot.lister()).toEqual(attendu.lignes);
        maintenant = new Date("2026-09-29T13:00:00Z");
        expect(await vidangeur.vidangerFileSortante()).toMatchObject({ envoyees: [], remisesEnAttente: [idA], bloquees: [idSuivant] });
        expect(appels).toEqual([requete(idA)]);
        const inconnue = (await depot.obtenir(idA))!;
        expect(inconnue).toEqual({ ...attendu.lignes.find(m => m.id === idA), tentatives: 2, prochaineTentativeA: "2026-09-29T13:00:02.000Z" });
        expect(inconnue.prochaineTentativeA).not.toBeNull();
        mauvaisRecu = false; maintenant = new Date("2026-09-29T14:00:00Z");
        expect(await vidangeur.vidangerFileSortante()).toMatchObject({ envoyees: [idA], bloquees: [idSuivant] });
        expect(await depot.obtenir(idA)).toEqual({ ...inconnue, statut: "envoyee", resumeAccepte: ack(idA) });
        const apresA = await depot.lister();
        expect(await depot.mettreAJourSiInchangee(avant, { ...inconnue, statut: "echec_permanent" })).toBe(false);
        expect(await depot.lister()).toEqual(apresA);
        expect((await vidangeur.vidangerFileSortante()).envoyees).toEqual([idSuivant]);
        expect(appels).toEqual([requete(idA), requete(idA), requete(idSuivant)]);
        expect(await depot.obtenir(idSuivant)).toMatchObject({ statut: "envoyee", resumeAccepte: ack(idSuivant) });
        terminales = await depot.lister();
        expect((await vidangeur.vidangerFileSortante()).envoyees).toEqual([]);
        expect(appels).toHaveLength(3); expect(await depot.lister()).toEqual(terminales);
      } finally { brute.close(); }
      const rouverte = baseReelle(fichier);
      try {
        await initialiserSchemaOutbox(rouverte.base);
        expect(await creerDepotOutboxSqlite(rouverte.base).lister()).toEqual(terminales!);
        if (externe) writeFileSync(`${fichier}.reprise.json`, JSON.stringify({ fictif: true, pid: process.pid,
          pidPreparation: attendu.pid, lignes: terminales }), { flag: "wx" });
      } finally { rouverte.brute.close(); }
    }
  } finally {
    // Seul le répertoire temporaire créé par CE test est nettoyé ; les preuves externes restent.
    if (dossier !== null) rmSync(dossier, { recursive: true, force: true });
  }
});
