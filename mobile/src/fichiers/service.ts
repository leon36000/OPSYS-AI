import type { FichierPreuveLocal } from "../m6/materiauxAvecPreuves";
import { deduireTypeMimeDepuisUri } from "./candidats";
import { File, Paths } from "expo-file-system";
import * as Crypto from "expo-crypto";
import NetInfo from "@react-native-community/netinfo";
import { candidatSignature, candidatsPhotosApres, preparerEnvoiFichier } from "./envoiOrchestrateur";
import type { ConfigurationEnvoiFichier, ResultatPreparationEnvoiFichier, CandidatFichierM4 } from "./envoiOrchestrateur";
import { construireArgumentsEtatFichier, interpreterResultatEtatFichier } from "./protocole";
import type { FonctionDigestSha256 } from "./empreinte";
import { genererMutationId } from "../outbox/id";
import { obtenirDepot } from "../outbox/service";
import type { DepotOutbox } from "../outbox/depot";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { capturerSessionMateriauxLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";

export interface EnvoiFichierChantier {
  readonly mutationId: string;
  readonly sha256: string;
  readonly resultat: ResultatPreparationEnvoiFichier;
}
/** Emplacement géré seulement. Rejette traversal avant URL (qui normaliserait les '..').
 * Le nom de fichier est l'UUID FS, distinct de l'UUID de la capture outbox. */
export function uriFichierGere(uri: string, chantier: string, mime: string | null, document: string, naturePhoto="apres"): boolean {
  try {
    const u = new URL(uri), root = new URL(document);
    if (u.protocol !== "file:" || root.protocol !== "file:" || u.host || u.search || u.hash || root.host) return false;
    const segments = uri.split(/[\\/]/).map(decodeURIComponent);
    if (segments.some(s => s === "." || s === ".." || /[\p{Cc}\p{Cs}\\]/u.test(s) || s.includes("/"))) return false;
    const prefix = root.pathname.endsWith("/") ? root.pathname : `${root.pathname}/`;
    if (!u.pathname.startsWith(prefix)) return false;
    const parts = u.pathname.slice(prefix.length).split("/").map(decodeURIComponent);
    const nom = parts[parts.length - 1];
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|jpeg|png)$/.test(nom)) return false;
    if (parts[1] !== chantier || !chantier || chantier === "." || chantier === ".." || /[\\/\p{Cc}\p{Cs}]/u.test(chantier)) return false;
    const extensionMime = nom.endsWith(".png") ? "image/png" : "image/jpeg";
    return mime === extensionMime && ((parts.length === 4 && parts[0] === "opsys-photos" && parts[2] === naturePhoto) ||
      (parts.length === 3 && parts[0] === "opsys-signatures"));
  } catch { return false; }
}
interface DependancesFichiers {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => Promise<{ readonly enLigne: boolean; readonly courante: () => boolean; readonly fermer: () => void }>;
  readonly obtenirDepot: () => Promise<DepotOutbox>;
  readonly lireOctets: ConfigurationEnvoiFichier["lireOctets"];
  readonly digest: FonctionDigestSha256;
  readonly genererId: () => string;
  readonly horloge: () => ConfigurationEnvoiFichier["horloge"];
  readonly documentUri: () => string;
  readonly appelerOutil: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
}
/** Une capture par invocation, avant bootstrap ; aucune autorité mutable partagée ni cache. */
export function creerServiceEnvoiFichiers(d: DependancesFichiers) {
  const envoyer=async (chantierId: string, couranteExterne: () => boolean = () => true, choisies?:readonly FichierPreuveLocal[]): Promise<EnvoiFichierChantier[]> => {
    const capture = d.capturerSession(), session = capture.session;
    if (!session || !capture.courante() || !couranteExterne()) return [];
    const reseau = await d.capturerReseau();
    const courante = () => capture.courante() && couranteExterne() && reseau.enLigne && reseau.courante();
    try {
      if (!courante()) return [];
      const depot = await d.obtenirDepot(); if (!courante()) return [];
      const mutations = await depot.lister(); if (!courante()) return [];
      if (copierJsonLecture(mutations) === JSON_LECTURE_INVALIDE) throw new Error("Captures locales illisibles ; aucune pièce effacée.");
      const signature = candidatSignature(mutations,chantierId,session.personne);
      let candidats:CandidatFichierM4[];
      const natures=new Map<string,string>();
      if(choisies){
        const snap=copierJsonLecture(choisies);if(snap===JSON_LECTURE_INVALIDE)throw new Error("Sélection illisible.");
        candidats=[];
        for(const attendu of choisies){
          const m=mutations.find(m=>m.id===attendu.capture_id&&m.type==="photo_upload"&&m.statut==="brouillon"&&m.proprietaire===session.personne&&m.chantierId===chantierId);
          if(!m||typeof m.payload.uri!=="string"||m.payload.sha256!==attendu.empreinte_sha256||m.payload.taille_octets!==attendu.taille_octets||deduireTypeMimeDepuisUri(m.payload.uri)!==attendu.type_mime||
            !(m.payload.nature==="avant"||m.payload.nature==="pendant"||m.payload.nature==="apres"))throw new Error("Capture choisie absente ou changée.");
          natures.set(m.id,m.payload.nature);candidats.push({mutationId:m.id,proprietaire:session.personne,chantierId,uri:m.payload.uri,sha256:attendu.empreinte_sha256,tailleOctets:attendu.taille_octets,typeMime:attendu.type_mime});
        }
      } else candidats=[...candidatsPhotosApres(mutations,chantierId,session.personne),...(signature?[signature]:[])];
      const config: ConfigurationEnvoiFichier = { depot, proprietaire:session.personne,courante,lireOctets:d.lireOctets,
        digest:d.digest,genererId:d.genererId,horloge:d.horloge(),
        verifierCandidat: async (fichier: CandidatFichierM4) => {
          if (!courante() || !uriFichierGere(fichier.uri,fichier.chantierId,fichier.typeMime,d.documentUri(),natures.get(fichier.mutationId)??"apres")) return false;
          const m = copierJsonLecture(await depot.obtenir(fichier.mutationId));
          if (!courante() || m === JSON_LECTURE_INVALIDE || typeof m !== "object" || m === null || Array.isArray(m) ||
            typeof m.payload !== "object" || m.payload === null || Array.isArray(m.payload)) return false;
          return m.id === fichier.mutationId && m.proprietaire === session.personne && m.chantierId === chantierId && m.statut === "brouillon" &&
            ((m.type === "photo_upload" && m.payload.nature === (natures.get(fichier.mutationId)??"apres")) || m.type === "signature_capture") &&
            m.payload.uri === fichier.uri && m.payload.sha256 === fichier.sha256 && m.payload.taille_octets === fichier.tailleOctets;
        },
        obtenirEtatServeur: async contexte => {
          if (!courante()) return null;
          const appel = await d.appelerOutil({fetchImpl:d.fetchImpl,urlBase:session.urlBase,jeton:session.jeton,
            requete:{tool:"m4_etat_fichier",args:{...construireArgumentsEtatFichier(contexte.empreinte_sha256)},deviceId:session.appareilId}});
          if (!courante() || !appel.ok) return null;
          const lecture = interpreterResultatEtatFichier(appel.result,contexte);
          return lecture.accepte ? lecture.resultat : {refus:lecture.verdict};
        } };
      const resultats: EnvoiFichierChantier[] = [];
      for (const candidat of candidats) {
        if (!courante()) break;
        const resultat = await preparerEnvoiFichier(config,candidat,[]);
        resultats.push({mutationId:candidat.mutationId,sha256:candidat.sha256,resultat});
        if (!courante()) break;
      }
      return resultats;
    } finally { reseau.fermer(); }
  };
  return {envoyer:(chantierId:string,courante?:()=>boolean)=>envoyer(chantierId,courante),
    envoyerSelection:(chantierId:string,fichiers:readonly FichierPreuveLocal[],courante?:()=>boolean)=>envoyer(chantierId,courante,fichiers)};
}
async function capturerReseauNatif() {
  let valeur: boolean | null = null, generation = 0;
  const observe = (v: boolean) => { if (valeur !== null && valeur !== v) generation++; valeur=v; };
  const fermer = NetInfo.addEventListener(s => observe(s.isConnected === true && s.isInternetReachable !== false));
  try {
    const s = await NetInfo.fetch(); observe(s.isConnected === true && s.isInternetReachable !== false);
    const enLigne = valeur === true;
    return {enLigne,courante:()=>enLigne && valeur === true && generation === 0,fermer};
  } catch { fermer();return {enLigne:false,courante:()=>false,fermer:()=>undefined}; }
}
const service = creerServiceEnvoiFichiers({capturerSession:capturerSessionMateriauxLecture,capturerReseau:capturerReseauNatif,
  obtenirDepot,lireOctets:uri=>new File(uri).bytes(),digest:octets=>Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256,octets),
  genererId:genererMutationId,horloge:()=>({maintenant:new Date(),decalageMinutesUTC:-new Date().getTimezoneOffset()}),
  documentUri:()=>Paths.document.uri,appelerOutil:invoquerOutil,fetchImpl:(input,init)=>fetch(input,init)});
export function envoyerFichiersDuChantier(chantierId: string, courante?: () => boolean): Promise<EnvoiFichierChantier[]> {
  return service.envoyer(chantierId,courante);
}

/** Sélection figée explicite : zéro fichier n'est choisi automatiquement pour une preuve M6. */
export function envoyerFichiersPreuvesSelectionnes(chantierId:string,fichiers:readonly FichierPreuveLocal[],courante:()=>boolean):Promise<EnvoiFichierChantier[]> {
  return service.envoyerSelection(chantierId,fichiers,courante);
}
