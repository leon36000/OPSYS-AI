import fs from "node:fs";
import path from "node:path";

import { definirConfigurationAppel, definirPersonneConfirmee, obtenirSessionEnvoi } from "../protocole/configuration";
import type { EtatIdentite } from "./etat";
import { synchroniserPersonneConfirmee } from "./sessionEnvoi";

const CONFIG_1 = { urlBase: "https://grs.exemple.ca", jeton: "jeton-1", appareilId: "APPAREIL-1" };
const CONFIG_2 = { ...CONFIG_1, jeton: "jeton-2" };
const IDENTITE = { appareilId: "APPAREIL-1", personne: "jdupont", role: "employee" } as const;

const CONFIRMEE: EtatIdentite = { genre: "confirmee", identite: IDENTITE };
const A_RECONFIRMER: EtatIdentite = { genre: "a_reconfirmer", identite: IDENTITE, confirmeLe: "2026-09-29T12:00:00.000Z" };

afterEach(() => {
  definirConfigurationAppel(null);
  definirPersonneConfirmee(null);
});

describe("synchroniserPersonneConfirmee : ce que la file sortante sait de la personne", () => {
  test("identité confirmée : la file peut envoyer pour cette personne, avec le jeton de cette configuration", () => {
    definirConfigurationAppel(CONFIG_1);
    synchroniserPersonneConfirmee(CONFIRMEE, CONFIG_1);
    expect(obtenirSessionEnvoi()).toEqual({ ...CONFIG_1, personne: "jdupont" });
  });

  test("identité gardée et à reconfirmer (hors ligne) : la file peut envoyer aussi", () => {
    definirConfigurationAppel(CONFIG_1);
    synchroniserPersonneConfirmee(A_RECONFIRMER, CONFIG_1);
    expect(obtenirSessionEnvoi()).toEqual({ ...CONFIG_1, personne: "jdupont" });
  });

  test.each<[string, EtatIdentite]>([
    ["restauration", { genre: "restauration" }],
    ["non_appairee", { genre: "non_appairee" }],
    ["en_lecture (juste après un appairage)", { genre: "en_lecture" }],
    ["erreur : jeton refusé", { genre: "erreur", motif: "jeton_refuse" }],
    ["erreur : appareil non attribué", { genre: "erreur", motif: "appareil_non_attribue" }],
    ["erreur : hors ligne sans mémoire", { genre: "erreur", motif: "hors_ligne_sans_memoire" }],
  ])("%s : plus aucune personne, la file n'envoie rien", (_nom, etat) => {
    definirConfigurationAppel(CONFIG_1);
    synchroniserPersonneConfirmee(CONFIRMEE, CONFIG_1);
    expect(obtenirSessionEnvoi()).not.toBeNull();

    synchroniserPersonneConfirmee(etat, CONFIG_1);

    expect(obtenirSessionEnvoi()).toBeNull();
  });

  test("coffre illisible : rien n'a changé en mémoire, la personne déjà confirmée pour ce jeton reste", () => {
    definirConfigurationAppel(CONFIG_1);
    synchroniserPersonneConfirmee(CONFIRMEE, CONFIG_1);

    synchroniserPersonneConfirmee({ genre: "erreur", motif: "stockage_illisible" }, null);

    expect(obtenirSessionEnvoi()).toEqual({ ...CONFIG_1, personne: "jdupont" });
  });

  test("l'identité est liée au jeton de la configuration lue : un résultat pour l'ancien jeton ne sert pas au nouveau", () => {
    definirConfigurationAppel(CONFIG_2); // nouvel appairage déjà posé
    synchroniserPersonneConfirmee(CONFIRMEE, CONFIG_1); // lecture terminée pour l'ANCIEN jeton
    expect(obtenirSessionEnvoi()).toBeNull();

    synchroniserPersonneConfirmee(CONFIRMEE, CONFIG_2);
    expect(obtenirSessionEnvoi()).toEqual({ ...CONFIG_2, personne: "jdupont" });
  });

  test("une identité d'un autre appareil que celui de la configuration n'est jamais retenue", () => {
    definirConfigurationAppel(CONFIG_1);
    const autreAppareil: EtatIdentite = { genre: "confirmee", identite: { ...IDENTITE, appareilId: "APPAREIL-9" } };
    synchroniserPersonneConfirmee(autreAppareil, CONFIG_1);
    expect(obtenirSessionEnvoi()).toBeNull();
  });

  test("une identité sans configuration n'ouvre rien", () => {
    synchroniserPersonneConfirmee(CONFIRMEE, null);
    expect(obtenirSessionEnvoi()).toBeNull();
  });
});

describe("le cycle d'identité ne change jamais d'état sans le dire à la file sortante", () => {
  // Les hooks ne sont pas testés en rendu (pas de bibliothèque de test de rendu) : ce garde lit la source,
  // comme `ecransSansSaisie.test.ts`, pour qu'aucun futur `definirEtat` ne contourne la synchronisation.
  const source = fs.readFileSync(path.join(__dirname, "hooks.ts"), "utf8");

  test("le seul appel direct à l'état de l'app est celui qui synchronise d'abord la file", () => {
    expect(source.match(/definirEtatApp\(/g)).toHaveLength(1);
    expect(source).toMatch(/synchroniserPersonneConfirmee\(etat, configuration\);\s*definirEtatApp\(etat\);/);
  });

  test("chaque changement d'état du cycle passe la configuration à laquelle il se rapporte", () => {
    const appels = source.match(/definirEtat\((?!etat: EtatIdentite)[^;]*;/g) ?? [];
    expect(appels).toHaveLength(3);
    for (const appel of appels) {
      expect(appel).toMatch(/,\s*(configuration|obtenirConfigurationAppel\(\))\)/);
    }
  });
});
