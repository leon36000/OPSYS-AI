import { ouvrirEnveloppe } from "../admin/enveloppe";
import { prototypeJsonValide } from "../m10/json";
import type { Reponse } from "../m7/contrat";

export type DigestM1 = string;
export type TypeTransfertM1 = "ventes" | "estimation" | "admin" | "finance" | "plainte" | "urgence" | "technique" | "proprietaire";
export interface VerdictM1 { readonly code: string; readonly detail: string; readonly statut?: string }
export interface ContactM1 { readonly telephone?: string; readonly courriel?: string }
export interface MessageTransfertM1 { readonly signal_id: string; readonly recu_le: string; readonly texte: string }
export interface GabaritM1 { readonly version: string; readonly statut_validation: string }
export interface ClotureTransfertM1 {
  readonly par: string; readonly role: "admin" | "nathan_owner"; readonly voie: "appareil" | "approbation";
  readonly motif: string; readonly clos_le: string;
}
export interface SuiviRappelM1 {
  readonly snapshot_suivi: string; readonly responsable: string | null; readonly role: "admin" | "nathan_owner" | null;
  readonly pris_en_charge_le: string | null; readonly tentatives_sans_contact: number;
  readonly derniere_tentative_le: string | null; readonly prochaine_tentative_le: string | null;
}
export interface TransfertM1 {
  readonly transfert_id: string; readonly statut: "ouvert" | "clos"; readonly type_transfert: TypeTransfertM1;
  readonly niveau: "N3" | "N4" | "N5"; readonly categories: readonly string[];
  readonly termes: Readonly<Record<string, readonly string[]>>; readonly declenche_par: "regles" | "agent";
  readonly canal: "telephone" | "courriel" | "formulaire" | "texte"; readonly conversation_id: string;
  readonly ouvert_le: string; readonly destinataire: string | null; readonly verdict_destinataire: VerdictM1 | null;
  readonly contact: ContactM1 | null; readonly lead_id: string | null; readonly resume: string; readonly resume_origine: "code" | "agent";
  readonly messages_couverts: readonly MessageTransfertM1[]; readonly messages_couverts_omis: number;
  readonly messages_suivants: readonly MessageTransfertM1[]; readonly messages_suivants_omis: number;
  readonly client_retire_des_messages: boolean; readonly cloture?: ClotureTransfertM1; readonly suivi_rappel?: SuiviRappelM1;
  readonly brouillon_reponse?: string | null; readonly envoye?: false; readonly gabarit?: GabaritM1; readonly sans_brouillon?: string;
}
const INVALIDE = Symbol("json_invalide");
const texte = (v: unknown): v is string => typeof v === "string" && v.trim() !== "";
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const longueur = (v: string): number => Array.from(v).length; // Même unité que len(str) du producteur Python.
const dans = <T extends string>(v: unknown, valeurs: readonly T[]): v is T => typeof v === "string" && valeurs.some(x => x === v);
function ferme(v: Record<string, unknown>, requis: readonly string[], optionnels: readonly string[] = []): boolean {
  return requis.every(k => Object.hasOwn(v, k)) && Object.keys(v).every(k => requis.includes(k) || optionnels.includes(k));
}
/** Copie avant lecture : getters, prototypes exotiques, cycles, trous et nombres non JSON ne sont jamais lus. */
function copier(v: unknown, profondeur = 14, vus = new Set<object>()): unknown {
  if (profondeur < 0) return INVALIDE;
  if (v === null || typeof v === "string" || typeof v === "boolean") return v;
  if (typeof v === "number") return Number.isFinite(v) && (!Number.isInteger(v) || Number.isSafeInteger(v)) ? v : INVALIDE;
  if (typeof v !== "object" || vus.has(v)) return INVALIDE;
  try {
    if (!prototypeJsonValide(v) || Reflect.ownKeys(v).some(k => typeof k !== "string")) return INVALIDE;
    vus.add(v);
    const ds = Object.getOwnPropertyDescriptors(v);
    if (Array.isArray(v)) {
      const n: unknown = ds.length?.value;
      if (!entier(n) || n > 4096 || Object.keys(ds).length !== n + 1) return INVALIDE;
      const r: unknown[] = [];
      for (let i = 0; i < n; i++) {
        const d = Object.hasOwn(ds, String(i)) ? ds[String(i)] : null;
        if (!d || !("value" in d)) return INVALIDE;
        const c = copier(d.value, profondeur - 1, vus); if (c === INVALIDE) return INVALIDE; r.push(c);
      }
      return r;
    }
    const r: Record<string, unknown> = Object.create(null);
    for (const [k, d] of Object.entries(ds)) {
      if (!("value" in d)) return INVALIDE;
      const c = copier(d.value, profondeur - 1, vus); if (c === INVALIDE) return INVALIDE; r[k] = c;
    }
    return r;
  } catch { return INVALIDE; } finally { vus.delete(v); }
}
export function dateDigestM1Valide(v: unknown): v is string {
  if (typeof v !== "string" || v.length !== 10 || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(v)) return false;
  const an = Number(v.slice(0, 4)), mois = Number(v.slice(5, 7)), jour = Number(v.slice(8, 10));
  const jours = [31, an % 4 === 0 && (an % 100 !== 0 || an % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return an > 0 && mois >= 1 && mois <= 12 && jour >= 1 && jour <= jours[mois - 1];
}
export function identifiantTransfertM1Valide(v: unknown): v is string {
  return typeof v === "string" && v.length === 23 && /^tr-[0-9a-f]{20}$/.test(v);
}
function instant(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-](\d{2}):(\d{2}))$/.exec(v);
  return m !== null && m[0].length === v.length && dateDigestM1Valide(m[1]) && Number(m[2]) < 24 && Number(m[3]) < 60 && Number(m[4]) < 60 &&
    (m[6] === undefined || Number(m[6]) < 24 && Number(m[7]) < 60);
}
function verdict(v: unknown): VerdictM1 | null | undefined {
  if (v === null) return null;
  if (!objet(v) || !ferme(v, ["code", "detail"], ["statut"]) || !texte(v.code) || typeof v.detail !== "string" ||
    Object.hasOwn(v, "statut") && typeof v.statut !== "string") return undefined;
  return { code: v.code, detail: v.detail, ...(typeof v.statut === "string" ? { statut: v.statut } : {}) };
}
function contact(v: unknown): ContactM1 | null | undefined {
  if (v === null) return null;
  if (!objet(v) || !ferme(v, [], ["telephone", "courriel"]) || Object.keys(v).length === 0 ||
    Object.values(v).some(x => !texte(x))) return undefined;
  return { ...(typeof v.telephone === "string" ? { telephone: v.telephone } : {}), ...(typeof v.courriel === "string" ? { courriel: v.courriel } : {}) };
}
function messages(v: unknown): MessageTransfertM1[] | undefined {
  if (!Array.isArray(v) || v.length > 4) return undefined;
  const r: MessageTransfertM1[] = [];
  for (const m of v) {
    if (!objet(m) || !ferme(m, ["signal_id", "recu_le", "texte"]) || !texte(m.signal_id) || !instant(m.recu_le) || typeof m.texte !== "string" || longueur(m.texte) > 350) return undefined;
    r.push({ signal_id: m.signal_id, recu_le: m.recu_le, texte: m.texte });
  }
  return r;
}
function cloture(v: unknown): ClotureTransfertM1 | undefined {
  if (!objet(v) || !ferme(v, ["par", "role", "voie", "motif", "clos_le"]) || !texte(v.par) || !dans(v.role, ["admin", "nathan_owner"] as const) ||
    !dans(v.voie, ["appareil", "approbation"] as const) || !texte(v.motif) || longueur(v.motif.trim()) < 10 || longueur(v.motif.trim()) > 500 || !instant(v.clos_le)) return undefined;
  return { par: v.par, role: v.role, voie: v.voie, motif: v.motif, clos_le: v.clos_le };
}
function rappel(v: unknown): SuiviRappelM1 | undefined {
  if (!objet(v) || !ferme(v, ["snapshot_suivi", "responsable", "role", "pris_en_charge_le", "tentatives_sans_contact", "derniere_tentative_le", "prochaine_tentative_le"]) ||
    typeof v.snapshot_suivi !== "string" || v.snapshot_suivi.length !== 64 || !/^[0-9a-f]{64}$/.test(v.snapshot_suivi) ||
    !(v.responsable === null || texte(v.responsable)) || !(v.role === null || dans(v.role, ["admin", "nathan_owner"] as const)) ||
    !(v.pris_en_charge_le === null || instant(v.pris_en_charge_le)) || !entier(v.tentatives_sans_contact) ||
    !(v.derniere_tentative_le === null || instant(v.derniere_tentative_le)) || !(v.prochaine_tentative_le === null || instant(v.prochaine_tentative_le))) return undefined;
  if (v.responsable === null ? v.role !== null || v.pris_en_charge_le !== null || v.tentatives_sans_contact !== 0 : v.role === null || v.pris_en_charge_le === null) return undefined;
  if (v.tentatives_sans_contact === 0 ? v.derniere_tentative_le !== null || v.prochaine_tentative_le !== null : v.derniere_tentative_le === null) return undefined;
  return { snapshot_suivi: v.snapshot_suivi, responsable: v.responsable, role: v.role, pris_en_charge_le: v.pris_en_charge_le,
    tentatives_sans_contact: v.tentatives_sans_contact, derniere_tentative_le: v.derniere_tentative_le, prochaine_tentative_le: v.prochaine_tentative_le };
}
function transfert(v: unknown): TransfertM1 | undefined {
  const requis = ["transfert_id", "statut", "type_transfert", "niveau", "categories", "termes", "declenche_par", "canal", "conversation_id", "ouvert_le", "destinataire", "verdict_destinataire", "contact", "lead_id", "resume", "resume_origine", "messages_couverts", "messages_couverts_omis", "messages_suivants", "messages_suivants_omis", "client_retire_des_messages"];
  if (!objet(v) || !ferme(v, requis, ["cloture", "suivi_rappel", "brouillon_reponse", "envoye", "gabarit", "sans_brouillon"]) || !identifiantTransfertM1Valide(v.transfert_id) ||
    !dans(v.statut, ["ouvert", "clos"] as const) || !dans(v.type_transfert, ["ventes", "estimation", "admin", "finance", "plainte", "urgence", "technique", "proprietaire"] as const) ||
    !dans(v.niveau, ["N3", "N4", "N5"] as const) || !Array.isArray(v.categories) || v.categories.some(x => !dans(x, ["insatisfaction", "degat", "garantie", "avocat", "securite"])) ||
    new Set(v.categories).size !== v.categories.length || !objet(v.termes) || !dans(v.declenche_par, ["regles", "agent"] as const) ||
    !dans(v.canal, ["telephone", "courriel", "formulaire", "texte"] as const) || !texte(v.conversation_id) || !instant(v.ouvert_le) ||
    !(v.destinataire === null || dans(v.destinataire, ["nathan_owner", "admin", "finance", "manager", "seller", "employee"])) || !(v.lead_id === null || texte(v.lead_id)) ||
    !texte(v.resume) || longueur(v.resume) > 1200 || !dans(v.resume_origine, ["code", "agent"] as const) ||
    !entier(v.messages_couverts_omis) || !entier(v.messages_suivants_omis) || typeof v.client_retire_des_messages !== "boolean") return undefined;
  const termes: Record<string, readonly string[]> = Object.create(null);
  for (const [k, ts] of Object.entries(v.termes)) {
    if (!v.categories.includes(k) || !Array.isArray(ts) || ts.some(x => !texte(x))) return undefined;
    termes[k] = ts;
  }
  const attendu = v.type_transfert === "urgence" || v.categories.includes("avocat") ? "N5" : v.type_transfert === "plainte" || v.type_transfert === "proprietaire" ? "N4" : "N3";
  const vd = verdict(v.verdict_destinataire), c = contact(v.contact), couverts = messages(v.messages_couverts), suivants = messages(v.messages_suivants);
  if (v.niveau !== attendu || vd === undefined || c === undefined || !couverts || !suivants ||
    (v.destinataire === null ? vd === null : vd !== null) || couverts.length + v.messages_couverts_omis > 6 ||
    v.messages_couverts_omis > 0 && couverts.length !== 4 || v.messages_suivants_omis > 0 && suivants.length !== 4) return undefined;
  const clos = Object.hasOwn(v, "cloture") ? cloture(v.cloture) : undefined;
  const suivi = Object.hasOwn(v, "suivi_rappel") ? rappel(v.suivi_rappel) : undefined;
  if ((v.statut === "clos" ? !clos : Object.hasOwn(v, "cloture")) || Object.hasOwn(v, "suivi_rappel") && (!suivi || v.type_transfert !== "ventes")) return undefined;
  const avecBrouillon = v.statut === "ouvert" && (v.type_transfert === "plainte" || v.type_transfert === "urgence");
  let gabarit: GabaritM1 | undefined;
  let brouillon: string | null | undefined;
  if (avecBrouillon) {
    if (!(v.brouillon_reponse === null || texte(v.brouillon_reponse)) || v.envoye !== false || !objet(v.gabarit) || !ferme(v.gabarit, ["version", "statut_validation"]) || !texte(v.gabarit.version) || !texte(v.gabarit.statut_validation)) return undefined;
    if (v.brouillon_reponse === null ? !texte(v.sans_brouillon) : Object.hasOwn(v, "sans_brouillon") || v.client_retire_des_messages || v.categories.includes("avocat")) return undefined;
    if (v.client_retire_des_messages && v.sans_brouillon !== "retrait_consentement" || !v.client_retire_des_messages && v.categories.includes("avocat") && v.sans_brouillon !== "sujet_legal_reponse_humaine") return undefined;
    gabarit = { version: v.gabarit.version, statut_validation: v.gabarit.statut_validation };
    brouillon = v.brouillon_reponse;
  } else if (["brouillon_reponse", "envoye", "gabarit", "sans_brouillon"].some(k => Object.hasOwn(v, k))) return undefined;
  return { transfert_id: v.transfert_id, statut: v.statut, type_transfert: v.type_transfert, niveau: v.niveau,
    categories: v.categories, termes, declenche_par: v.declenche_par, canal: v.canal, conversation_id: v.conversation_id, ouvert_le: v.ouvert_le,
    destinataire: v.destinataire, verdict_destinataire: vd, contact: c, lead_id: v.lead_id, resume: v.resume, resume_origine: v.resume_origine,
    messages_couverts: couverts, messages_couverts_omis: v.messages_couverts_omis, messages_suivants: suivants, messages_suivants_omis: v.messages_suivants_omis,
    client_retire_des_messages: v.client_retire_des_messages, ...(clos ? { cloture: clos } : {}), ...(suivi ? { suivi_rappel: suivi } : {}),
    ...(avecBrouillon && gabarit && brouillon !== undefined ? { brouillon_reponse: brouillon, envoye: false as const, gabarit,
      ...(typeof v.sans_brouillon === "string" ? { sans_brouillon: v.sans_brouillon } : {}) } : {}) };
}
function digestValide(v: unknown): v is string {
  if (typeof v !== "string" || longueur(v) > 6000 || /[\r\0]/.test(v)) return false;
  const absence = /^Absence d'activité enregistrée pour la période de référence ([0-9]{4}-[0-9]{2}-[0-9]{2})\.$/.exec(v);
  if (absence) return absence[0].length === v.length && dateDigestM1Valide(absence[1]);
  const lignes = v.split("\n"), entete = /^DIGEST - Période de référence : ([0-9]{4}-[0-9]{2}-[0-9]{2})$/.exec(lignes[0]);
  if (!entete || !dateDigestM1Valide(entete[1])) return false;
  const nombre = (s: string) => /^(0|[1-9][0-9]*)$/.test(s) && Number.isSafeInteger(Number(s));
  let i = 1;
  for (const canal of ["telephone", "courriel", "formulaire", "texte"]) for (const type of ["signal", "transition_phase", "lead_emis", "chiffrage_emis", "alerte"]) {
    const prefixe = `- ${canal}: ${type}: `; if (!lignes[i]?.startsWith(prefixe) || !nombre(lignes[i].slice(prefixe.length))) return false; i++;
  }
  for (const paire of [["- conversations ouvertes à suivre : ", "- conversations sans suivi à l'échéance de leur fenêtre : "], ["- transferts à un humain ouverts : ", "- dont urgences de sécurité : "]]) {
    if (!lignes[i]?.startsWith(paire[0])) continue;
    if (!nombre(lignes[i++].slice(paire[0].length)) || !lignes[i]?.startsWith(paire[1])) return false;
    const valeur = lignes[i++].slice(paire[1].length);
    if (paire[1].includes("urgences")) { const parts = valeur.split(", plaintes : "); if (parts.length !== 2 || !parts.every(nombre)) return false; }
    else if (!nombre(valeur)) return false;
  }
  if (lignes[i]?.startsWith("- appels importés : ")) {
    const statuts = lignes[i++].slice("- appels importés : ".length).split(", ");
    const noms: string[] = [];
    for (const s of statuts) { const [nom, n, extra] = s.split(": "); if (!dans(nom, ["manque", "voicemail", "inconnu"]) || !nombre(n) || extra !== undefined || noms.includes(nom)) return false; noms.push(nom); }
  }
  const dernier = "- entrées non classées : "; return i === lignes.length - 1 && lignes[i].startsWith(dernier) && nombre(lignes[i].slice(dernier.length));
}
const illisible = <T>(): Reponse<T> => ({ ok: false, code: "reponse_illisible", detail: "Lecture M1 illisible." });
export function lireTransfertM1(brut: unknown, transfertIdAttendu?: string): Reponse<TransfertM1> {
  const copie = copier(brut); if (copie === INVALIDE) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "couple"); if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  const v = transfert(ouverte.valeur);
  return v && (transfertIdAttendu === undefined || identifiantTransfertM1Valide(transfertIdAttendu) && v.transfert_id === transfertIdAttendu)
    ? { ok: true, value: v } : illisible();
}
export function lireDigestM1(brut: unknown, dateReferenceAttendue?: string): Reponse<DigestM1> {
  const copie = copier(brut); if (copie === INVALIDE) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "directe"); if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  const v = ouverte.valeur;
  return digestValide(v) && (dateReferenceAttendue === undefined || dateDigestM1Valide(dateReferenceAttendue) &&
    (v.startsWith(`DIGEST - Période de référence : ${dateReferenceAttendue}\n`) ||
      v === `Absence d'activité enregistrée pour la période de référence ${dateReferenceAttendue}.`))
    ? { ok: true, value: v } : illisible();
}
