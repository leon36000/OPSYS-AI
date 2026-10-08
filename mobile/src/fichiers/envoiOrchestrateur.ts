import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { encoderBase64Standard } from "./base64";
import { candidatsPhotosApres, candidatSignature } from "./candidats";
import type { CandidatFichierM4 } from "./candidats";
import { calculerEtatEnvoiFichier } from "./etatEnvoi";
import type { EtatEnvoiFichier } from "./etatEnvoi";
import { construireArgumentsDeposerFichier, interpreterResultatEtatFichier, lireContexteBlocFichier, lireMutationsFichiers } from "./protocole";
import type { ResultatEtatFichier, VerdictServeurFichier, ContexteEtatFichierM4 } from "./protocole";
import { validerTailleFichier, decouperEnBlocs } from "./decoupage";
import { verifierEmpreinteFichier } from "./verification";
import type { FonctionDigestSha256 } from "./empreinte";
import { creerMutation, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { DepotOutbox } from "../outbox/depot";
import type { MutationOutbox } from "../outbox/types";

/**
 * Orchestrateur d'ENVOI D'UN FICHIER par la file sortante (mission T1.4-f, item 1). Même
 * discipline que `src/today/orchestrateur.ts`/`src/outbox/vidangeur.ts` : orchestration PURE
 * côté logique (aucun accès fichier/réseau en dur), tout injecté par `ConfigurationEnvoiFichier`
 * — testable de bout en bout avec un dépôt mémoire, un lecteur de fichier factice et un `digest`
 * factice, JAMAIS contre un vrai serveur ni un vrai système de fichiers (mission, cadre de
 * travail). `src/fichiers/service.ts` fournit le câblage réel.
 *
 * Cette fonction ne fait qu'ENFILER les blocs manquants dans la file sortante (`brouillon` ->
 * `en_attente`, via `creerMutation`/`soumettreMutation`, même patron que tout le reste de
 * `src/outbox`) — l'ENVOI proprement dit reste le travail du vidangeur générique
 * (`src/outbox/vidangeur.ts`, via le descripteur `fichier_bloc` de `src/outbox/descripteurs.ts`),
 * jamais dupliqué ici : ce module ne fait jamais lui-même d'appel `/tools/invoke`, à L'EXCEPTION
 * de la lecture DIRECTE (pas par la file, comme `m4_statut_intervention`) de `m4_etat_fichier`
 * pour la REPRISE (voir `obtenirEtatServeur`).
 */
export interface ConfigurationEnvoiFichier {
  readonly depot: DepotOutbox;
  /** Lit les octets RÉELS du fichier local — injecté pour rester testable sans
   * `expo-file-system` (mission : jamais contre un vrai système de fichiers dans les tests). */
  readonly lireOctets: (uri: string) => Promise<Uint8Array<ArrayBuffer>>;
  readonly digest: FonctionDigestSha256;
  readonly genererId: () => string;
  readonly horloge: HorlogeAppareil;
  /** Query directe sous capture actuelle, après relecture taille/MIME/hash des octets.
   * Null ou refus ferme pret et conserve les captures/intentions ; aucun fallback local.
   * Le contexte4 est local, les seuls args RPC restent l'empreinte SHA. */
  readonly obtenirEtatServeur: (contexte: ContexteEtatFichierM4) => Promise<ResultatEtatFichier | { readonly refus: VerdictServeurFichier } | null>;
  readonly proprietaire: string;
  readonly courante: () => boolean;
  /** Relit la capture persistée/owner/cible/URI/hash avant chaque frontière, sans permission persistée. */
  readonly verifierCandidat: (fichier: CandidatFichierM4) => Promise<boolean>;
}

export type ResultatPreparationEnvoiFichier =
  | { readonly ok: true; readonly blocsEnfiles: number; readonly pret: boolean }
  | { readonly ok: false; readonly pret: false; readonly raison: "etat_refuse"; readonly verdict: VerdictServeurFichier }
  | { readonly ok: false; readonly pret: false; readonly raison: "taille_invalide"; readonly verdict: VerdictServeurFichier }
  | { readonly ok: false; readonly pret: false; readonly raison: "empreinte_discordante"; readonly sha256Capture: string; readonly sha256Relu: string }
  | { readonly ok: false; readonly pret: false; readonly raison: "type_non_permis" | "echec_permanent" | "contexte_change" |
      "etat_indisponible" | "fichier_invalide" | "taille_discordante" | "echec_lecture" };
const change = (): ResultatPreparationEnvoiFichier => ({ ok: false, pret: false, raison: "contexte_change" });
async function preparerSousVerrou(config: ConfigurationEnvoiFichier, fichier: CandidatFichierM4): Promise<ResultatPreparationEnvoiFichier> {
  const courant = () => config.courante() && config.proprietaire === fichier.proprietaire;
  const garde = async () => courant() && await config.verifierCandidat(fichier) && courant();
  if (!courant() || !await garde()) return change();
  if (fichier.typeMime === null) return { ok: false, pret: false, raison: "type_non_permis" };
  const verdict = validerTailleFichier(fichier.tailleOctets);
  if (verdict) return { ok: false, pret: false, raison: "taille_invalide", verdict };
  if (!/^[0-9a-f]{64}$/.test(fichier.sha256)) return { ok: false, pret: false, raison: "fichier_invalide" };
  const enBase = lireMutationsFichiers(await config.depot.lister()); if (!await garde() || !courant()) return change();
  if (!enBase) return { ok:false,pret:false,raison:"fichier_invalide" };
  const etatLocal = calculerEtatEnvoiFichier(enBase.filter(m => m.proprietaire === fichier.proprietaire), fichier.chantierId, fichier.sha256);
  if (etatLocal.statut === "echec_permanent") return { ok: false, pret: false, raison: "echec_permanent" };
  let octets: Uint8Array<ArrayBuffer>;
  try { if (!await garde() || !courant()) return change(); octets = await config.lireOctets(fichier.uri); }
  catch { return courant() ? { ok: false, pret: false, raison: "echec_lecture" } : change(); }
  if (!await garde() || !courant()) return change();
  if (octets.byteLength !== fichier.tailleOctets) return { ok: false, pret: false, raison: "taille_discordante" };
  // Même signature que fichiers.py ; vérification de format, ni décodage ni véracité de scène.
  const signature = fichier.typeMime === "image/jpeg" ? [0xff,0xd8,0xff] : [0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a];
  if (!signature.every((octet,index) => octets[index] === octet)) return { ok:false,pret:false,raison:"type_non_permis" };
  const verification = await verifierEmpreinteFichier(octets, fichier.sha256, config.digest);
  if (!await garde() || !courant()) return change();
  if (!verification.ok) return { ...verification, pret: false, raison: "empreinte_discordante" };
  const blocs = decouperEnBlocs(octets);
  const contexte: ContexteEtatFichierM4 = { empreinte_sha256: fichier.sha256, taille_octets: octets.byteLength,
    type_mime: fichier.typeMime, nombre_blocs: blocs.length };
  if (!await garde() || !courant()) return change();
  let observe: ResultatEtatFichier | { readonly refus: VerdictServeurFichier } | null;
  try { observe = await config.obtenirEtatServeur(contexte); } catch { observe = null; }
  if (!await garde() || !courant()) return change();
  // L'adaptateur decode la réponse entière ; une seconde validation ferme aussi les fakes/callers.
  const es = copierJsonLecture(observe);
  if (es !== JSON_LECTURE_INVALIDE && typeof es === "object" && es !== null && !Array.isArray(es) &&
    Object.keys(es).length === 1 && Object.hasOwn(es,"refus") && typeof es.refus === "object" && es.refus !== null && !Array.isArray(es.refus) &&
    Object.keys(es.refus).length === 2 && typeof es.refus.code === "string" && typeof es.refus.detail === "string")
    return { ok:false,pret:false,raison:"etat_refuse",verdict:{code:es.refus.code,detail:es.refus.detail} };
  if (es === JSON_LECTURE_INVALIDE || typeof es !== "object" || es === null || Array.isArray(es) ||
    Object.keys(es).length !== 4 || !["existe","complet","blocsRecus","reference"].every(k => Object.hasOwn(es,k)))
    return { ok:false,pret:false,raison:"etat_indisponible" };
  const interpretation = interpreterResultatEtatFichier({ ok: true, resultat: { accepte: true,
    resultat: { existe: es.existe, complet: es.complet, blocs_recus: es.blocsRecus, reference: es.reference } } }, contexte);
  if (!interpretation.accepte) return { ok: false, pret: false, raison: "etat_indisponible" };
  const etat = interpretation.resultat;
  const actuelles = lireMutationsFichiers(await config.depot.lister()); if (!await garde() || !courant()) return change();
  if (!actuelles) return { ok:false,pret:false,raison:"fichier_invalide" };
  const proches = actuelles.filter(m => (m.type === "fichier_bloc" || m.type === "fichier_bloc_reconcilie") &&
    m.chantierId === fichier.chantierId && m.payload.empreinte_sha256 === fichier.sha256);
  // Une absence actuelle ne justifie jamais de redéposer un ancien fichier annoncé envoyé.
  if (!etat.existe && proches.some(m => m.statut === "envoyee" || m.type === "fichier_bloc_reconcilie"))
    return { ok:false,pret:false,raison:"etat_indisponible" };
  for (const m of proches) {
    if (m.proprietaire !== fichier.proprietaire || m.statut === "echec_permanent") continue;
    const c = lireContexteBlocFichier(m);
    if (!c || Object.keys(contexte).some(k => Reflect.get(c.contexte,k) !== Reflect.get(contexte,k)) || !etat.blocsRecus.includes(c.index)) continue;
    if (!await garde() || !courant()) return change();
    await config.depot.mettreAJour({ ...m, statut: "envoyee", resumeAccepte: { genre: "etat_fichier", contexte, etat } });
    if (!await garde() || !courant()) return change();
  }
  const occupes = new Set(proches.map(m => m.payload.index_bloc));
  let blocsEnfiles = 0;
  for (let index = 0; index < blocs.length; index++) {
    // Aucune nouvelle clé pour contourner ancien owner/legacy/issue inconnue de cet indice.
    if (occupes.has(index) || etat.blocsRecus.includes(index)) continue;
    if (!await garde() || !courant()) return change();
    const args = construireArgumentsDeposerFichier(fichier.sha256, octets.byteLength, fichier.typeMime, index, blocs.length, encoderBase64Standard(blocs[index]));
    const m = soumettreMutation(creerMutation({ type: "fichier_bloc", chantierId: fichier.chantierId, payload: { ...args } }, config.genererId, config.horloge));
    await config.depot.inserer({ ...m, proprietaire: fichier.proprietaire });
    blocsEnfiles++; if (!await garde() || !courant()) return change();
  }
  if (!await garde() || !courant()) return change();
  return { ok: true, blocsEnfiles, pret: etat.complet };
}
const preparationsActives = new WeakMap<DepotOutbox, Map<string, Promise<ResultatPreparationEnvoiFichier>>>();
/** Sérialise, mais ne partage jamais le résultat/la capture d'une autre invocation. */
export function preparerEnvoiFichier(config: ConfigurationEnvoiFichier, candidat: CandidatFichierM4,
  _mutationsExistantes: readonly MutationOutbox[]): Promise<ResultatPreparationEnvoiFichier> {
  const copie = copierJsonLecture(candidat);
  if (copie === JSON_LECTURE_INVALIDE || typeof copie !== "object" || copie === null || Array.isArray(copie) ||
    Object.keys(copie).length !== 7 || typeof copie.mutationId !== "string" || !copie.mutationId || typeof copie.proprietaire !== "string" || !copie.proprietaire ||
    typeof copie.chantierId !== "string" || !copie.chantierId || typeof copie.uri !== "string" || !copie.uri || typeof copie.sha256 !== "string" ||
    typeof copie.tailleOctets !== "number" || !(copie.typeMime === null || copie.typeMime === "image/jpeg" || copie.typeMime === "image/png"))
    return Promise.resolve({ ok: false, pret: false, raison: "fichier_invalide" });
  const fichier: CandidatFichierM4 = { mutationId: copie.mutationId, proprietaire: copie.proprietaire, chantierId: copie.chantierId,
    uri: copie.uri, sha256: copie.sha256, tailleOctets: copie.tailleOctets, typeMime: copie.typeMime };
  let map = preparationsActives.get(config.depot); if (!map) { map = new Map(); preparationsActives.set(config.depot,map); }
  const cle = JSON.stringify([fichier.proprietaire,fichier.chantierId,fichier.sha256,fichier.uri]);
  const precedente = map.get(cle);
  const travail = (precedente ? precedente.catch(() => undefined) : Promise.resolve()).then(() => preparerSousVerrou(config,fichier))
    .finally(() => { if (map.get(cle) === travail) map.delete(cle); });
  map.set(cle,travail);return travail;
}

// Réexportés pour que les écrans/tests n'aient qu'un seul module à importer pour préparer la
// liste des fichiers candidats d'un chantier (photos « après » + signature) avant d'appeler
// `preparerEnvoiFichier` sur chacun.
export { candidatsPhotosApres, candidatSignature };
export type { CandidatFichierM4, EtatEnvoiFichier };
