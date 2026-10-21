import { ouvrirEnveloppe } from "../admin/enveloppe";
import type { Reponse } from "./contrat";

/** Vue de la file historique volatile. Aucun identifiant de décision durable ni droit de publication. */
export interface PropositionHistoriqueM7 {
  readonly id: string;
  readonly title: string;
  readonly body: string;
  readonly surface: "google_aio" | "perplexity" | "assistants_ia";
  readonly type: "post_social" | "page_seo" | "fiche_gbp" | "article_blog";
  readonly approval_status: "PROPOSE" | "APPROVED" | "REJECTED";
  readonly proposer: string;
  readonly propose_timestamp: string;
  readonly approver: string;
  readonly approval_timestamp: string;
  readonly timestamp: string;
}

/** Consentement à demander un avis : distinct du consentement à publier du contenu marketing. */
export interface DemandeAvisM7 {
  readonly id: string;
  readonly wct_id: string;
  readonly nature_travaux: string | null;
  readonly ville: string | null;
  readonly texte: string;
  readonly approval_status: "PROPOSE";
  readonly avertissements: readonly string[];
  readonly consentement: {
    readonly recueilli_par: string;
    readonly recueilli_le: string;
    readonly version_texte: string;
  };
}

const INVALIDE = Symbol("donnee_non_json");
const texte = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const entier = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const objet = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Copie de données propres AVANT ouvrirEnveloppe : aucun getter, héritage ou tableau creux n'est lu.
 * Valide aussi verdict/details ; les lecteurs communs peuvent ainsi les ouvrir sans exécuter d'accesseur. */
function copierDonnee(v: unknown, vus = new Set<object>()): unknown {
  if (v === null || typeof v === "string" || typeof v === "boolean") return v;
  if (typeof v === "number") return Number.isFinite(v) ? v : INVALIDE;
  if (typeof v !== "object" || vus.has(v)) return INVALIDE;
  try {
    vus.add(v);
    const proto = Object.getPrototypeOf(v);
    const tableau = Array.isArray(v);
    if (tableau ? proto !== Array.prototype : proto !== Object.prototype && proto !== null) return INVALIDE;
    const descriptors = Object.getOwnPropertyDescriptors(v);
    if (Reflect.ownKeys(v).some(cle => typeof cle !== "string")) return INVALIDE;
    if (tableau) {
      const longueur: unknown = descriptors.length?.value;
      if (!entier(longueur) || Object.keys(descriptors).length !== longueur + 1) return INVALIDE;
      const resultat: unknown[] = [];
      for (let i = 0; i < longueur; i++) {
        const d = Object.hasOwn(descriptors, String(i)) ? descriptors[String(i)] : null;
        if (!d || !("value" in d)) return INVALIDE;
        const copie = copierDonnee(d.value, vus);
        if (copie === INVALIDE) return INVALIDE;
        resultat.push(copie);
      }
      return resultat;
    }
    const resultat: Record<string, unknown> = Object.create(null);
    for (const [cle, d] of Object.entries(descriptors)) {
      if (!("value" in d)) return INVALIDE;
      const copie = copierDonnee(d.value, vus);
      if (copie === INVALIDE) return INVALIDE;
      resultat[cle] = copie;
    }
    return resultat;
  } catch {
    return INVALIDE;
  } finally {
    vus.delete(v);
  }
}

/** Forme ISO avec fuseau rendue par le serveur ; garde espace et microsecondes sans normaliser. */
function dateAvecFuseau(v: unknown): v is string {
  if (typeof v !== "string") return false;
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,]\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(v);
  if (!m) return false;
  const [, an, mois, jour, heure, minute, seconde, , decalageHeure, decalageMinute] = m;
  const a = Number(an), mo = Number(mois), j = Number(jour);
  const bissextile = a % 4 === 0 && (a % 100 !== 0 || a % 400 === 0);
  const jours = [31, bissextile ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return a > 0 && mo >= 1 && mo <= 12 && j >= 1 && j <= jours[mo - 1] &&
    Number(heure) < 24 && Number(minute) < 60 && Number(seconde) < 60 &&
    (decalageHeure === undefined || (Number(decalageHeure) < 24 && Number(decalageMinute) < 60));
}

function proposition(v: unknown): PropositionHistoriqueM7 | null {
  if (!objet(v) || !texte(v.id) || !texte(v.title) || !texte(v.body) ||
    (v.surface !== "google_aio" && v.surface !== "perplexity" && v.surface !== "assistants_ia") ||
    (v.type !== "post_social" && v.type !== "page_seo" && v.type !== "fiche_gbp" && v.type !== "article_blog") ||
    (v.approval_status !== "PROPOSE" && v.approval_status !== "APPROVED" && v.approval_status !== "REJECTED") ||
    !texte(v.proposer) || !dateAvecFuseau(v.propose_timestamp) || typeof v.approver !== "string" ||
    (v.approval_status !== "PROPOSE" && !texte(v.approver)) ||
    !(v.approval_timestamp === "" || dateAvecFuseau(v.approval_timestamp)) ||
    !(v.timestamp === "" || dateAvecFuseau(v.timestamp))) return null;
  return { id: v.id, title: v.title, body: v.body, surface: v.surface, type: v.type,
    approval_status: v.approval_status, proposer: v.proposer, propose_timestamp: v.propose_timestamp,
    approver: v.approver, approval_timestamp: v.approval_timestamp, timestamp: v.timestamp };
}

function demandeAvis(v: unknown): DemandeAvisM7 | null {
  if (!objet(v)) return null;
  const c = v.consentement;
  if (!texte(v.id) || !texte(v.wct_id) || !(v.nature_travaux === null || typeof v.nature_travaux === "string") ||
    !(v.ville === null || typeof v.ville === "string") || !texte(v.texte) || v.approval_status !== "PROPOSE" ||
    !Array.isArray(v.avertissements) || !v.avertissements.every(texte) || !objet(c) ||
    !texte(c.recueilli_par) || !dateAvecFuseau(c.recueilli_le) || !texte(c.version_texte)) return null;
  return { id: v.id, wct_id: v.wct_id, nature_travaux: v.nature_travaux, ville: v.ville, texte: v.texte,
    approval_status: v.approval_status, avertissements: [...v.avertissements],
    consentement: { recueilli_par: c.recueilli_par, recueilli_le: c.recueilli_le, version_texte: c.version_texte } };
}

function illisible<T>(): Reponse<T> {
  return { ok: false, code: "reponse_illisible", detail: "Réponse marketing illisible : aucune ligne partielle affichée." };
}
function lire<T>(brut: unknown, lireValeur: (v: unknown) => T | null): Reponse<T> {
  const copie = copierDonnee(brut);
  if (copie === INVALIDE) return illisible();
  const ouverte = ouvrirEnveloppe(copie, "directe");
  if (!ouverte.ok) return { ok: false, code: ouverte.verdict.code, detail: ouverte.verdict.detail };
  const value = lireValeur(ouverte.valeur);
  return value === null ? illisible() : { ok: true, value };
}

/** Le serveur rend un tableau sans plafond métier, total ni curseur. Une troncature reste un échec. */
export function lireFileApprobationM7(brut: unknown): Reponse<readonly PropositionHistoriqueM7[]> {
  return lire(brut, v => {
    if (!Array.isArray(v)) return null;
    const lignes: PropositionHistoriqueM7[] = [];
    const ids = new Set<string>();
    for (const element of v) {
      const ligne = proposition(element);
      if (!ligne || ids.has(ligne.id)) return null;
      ids.add(ligne.id);
      lignes.push(ligne);
    }
    return lignes;
  });
}

export function lireDemandesAvisM7(brut: unknown): Reponse<{ total: number; demandes: readonly DemandeAvisM7[]; reste: number }> {
  return lire(brut, v => {
    if (!objet(v) || !entier(v.total) || !entier(v.reste) || !Array.isArray(v.demandes) || v.demandes.length > 8 ||
      (v.demandes.length === 0 && v.total !== 0) || !Number.isSafeInteger(v.demandes.length + v.reste) ||
      v.total !== v.demandes.length + v.reste) return null;
    const demandes: DemandeAvisM7[] = [];
    const ids = new Set<string>(), wcts = new Set<string>();
    for (const element of v.demandes) {
      const ligne = demandeAvis(element);
      // Le consommateur natif ne crée qu'une demande par WCT, y compris après relivraison du bus.
      if (!ligne || ids.has(ligne.id) || wcts.has(ligne.wct_id)) return null;
      ids.add(ligne.id);
      wcts.add(ligne.wct_id);
      demandes.push(ligne);
    }
    return { total: v.total, demandes, reste: v.reste };
  });
}
