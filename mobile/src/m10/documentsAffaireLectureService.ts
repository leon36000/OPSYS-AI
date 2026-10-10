import { appelerLecture } from "../admin/appel";
import type { VerdictServeur } from "../outbox/vidangeur";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import type { Reponse } from "../m7/contrat";
import type { ReferenceDocumentM10 } from "./documentsAffaireOutbox";
import {
  construireArgumentsIndexDocumentsAffaireM10, construireArgumentsVersionDocumentAffaireM10,
  lireIndexDocumentsAffaireM10, lireVersionDocumentAffaireM10,
} from "./documentsAffaireLecture";
import type { IndexDocumentsAffaireM10, VersionDocumentAffaireM10 } from "./documentsAffaireLecture";

export type ResultatLectureDocumentAffaireM10<T> =
  | { readonly source: "serveur"; readonly valeur: T }
  | { readonly source: "refus"; readonly verdict: VerdictServeur }
  | { readonly source: "aucune"; readonly raison: VerdictServeur };
export interface DependancesDocumentsAffaireM10 {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly appelerOutil: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly enLigne: () => boolean;
}
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });
const CODES = new Set(["AUTORITE-INVALIDE", "MODE-NON-ADMIS", "FORME-INVALIDE", "AFFAIRE-INCONNUE",
  "REFERENCE-INVALIDE", "REGISTRE-INVALIDE", "CONNEXION-INVALIDE", "DIALECTE-NON-ADMIS",
  "QUOTA-DEPASSE", "INDISPONIBLE"].map(code => "REJ-M10-LECTURE-" + code));
function refusNomme(v: unknown): VerdictServeur | null {
  const copie = copierJsonLecture(v);
  if (copie === JSON_LECTURE_INVALIDE || typeof copie !== "object" || copie === null || Array.isArray(copie) ||
    Object.keys(copie).length !== 2 || !Object.hasOwn(copie, "ok") || !Object.hasOwn(copie, "erreur") ||
    copie.ok !== false || typeof copie.erreur !== "string" || !CODES.has(copie.erreur)) return null;
  return { code: copie.erreur, detail: "Lecture documentaire refusée par le serveur." };
}
function figer<A>(construire: () => A): A | typeof JSON_LECTURE_INVALIDE {
  try { return construire(); } catch { return JSON_LECTURE_INVALIDE; }
}

/** T0 sans dépôt, intention, horloge ni état partagé : chaque page est une lecture courante. */
export function creerChargeurDocumentsAffaireM10(d: DependancesDocumentsAffaireM10) {
  async function lire<A extends object, T>(outil: string, args: A | typeof JSON_LECTURE_INVALIDE,
    lecteur: (brut: unknown, arguments3: unknown) => Reponse<T>): Promise<ResultatLectureDocumentAffaireM10<T> | null> {
    const capture = d.capturerSession(), session = capture.session;
    if (!session) return null;
    // Primitives de la destination d'origine, capturées avant le premier await.
    const { urlBase, jeton } = session;
    if (!capture.courante()) return aucune("lecture_remplacee");
    if (args === JSON_LECTURE_INVALIDE) return aucune("lecture_arguments_invalides");
    if (!d.enLigne()) return aucune("hors_ligne");
    try {
      const appel = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase, jeton },
        outil, args as Readonly<Record<string, unknown>>);
      if (!capture.courante()) return aucune("lecture_remplacee");
      if (!d.enLigne()) return aucune("hors_ligne");
      if (appel.genre === "refuse") return { source: "refus", verdict: appel.verdict };
      if (appel.genre !== "reponse") return aucune("lecture_indisponible");
      const refus = refusNomme(appel.resultat);
      if (refus) return { source: "refus", verdict: refus };
      const lu = lecteur(appel.resultat, args);
      if (!capture.courante()) return aucune("lecture_remplacee");
      if (!d.enLigne()) return aucune("hors_ligne");
      return lu.ok ? { source: "serveur", valeur: lu.value } : aucune("reponse_illisible");
    } catch {
      if (!capture.courante()) return aucune("lecture_remplacee");
      return aucune(d.enLigne() ? "lecture_indisponible" : "hors_ligne");
    }
  }
  return {
    chargerIndex: (affaireId: string, decalage = 0, limite = 1) => {
      const args = figer(() => construireArgumentsIndexDocumentsAffaireM10(affaireId, decalage, limite));
      return lire("m10_lister_documents_affaire_appareil", args, lireIndexDocumentsAffaireM10);
    },
    chargerVersion: (affaireId: string, documentRef: ReferenceDocumentM10, versionSource: ReferenceDocumentM10) => {
      const args = figer(() => construireArgumentsVersionDocumentAffaireM10(affaireId, documentRef, versionSource));
      return lire("m10_lire_version_document_affaire_appareil", args, lireVersionDocumentAffaireM10);
    },
  };
}
function chargeur(enLigne: () => boolean) {
  return creerChargeurDocumentsAffaireM10({ capturerSession: capturerSessionAdminLecture,
    appelerOutil: invoquerOutil, fetchImpl: fetch, enLigne });
}
export function chargerIndexDocumentsAffaireM10(affaireId: string, decalage: number, limite: number,
  enLigne: () => boolean): Promise<ResultatLectureDocumentAffaireM10<IndexDocumentsAffaireM10> | null> {
  return chargeur(enLigne).chargerIndex(affaireId, decalage, limite);
}
export function chargerVersionDocumentAffaireM10(affaireId: string, documentRef: ReferenceDocumentM10,
  versionSource: ReferenceDocumentM10, enLigne: () => boolean): Promise<ResultatLectureDocumentAffaireM10<VersionDocumentAffaireM10> | null> {
  return chargeur(enLigne).chargerVersion(affaireId, documentRef, versionSource);
}
