import type { PhotoPreuveM6 } from '../m6/preuvesLecture';
export interface SelectionPhotoPreuve {
  readonly wct_id: string; readonly preuve: { readonly index: number; readonly hash_maillon: string };
  readonly position_photo: number;
}
export interface TemporairePreuve {
  readonly uri: string; ecrire(bytes: Uint8Array): void; fermer(): void;
  taille(): number; empreinte(): Promise<string>; supprimer(): void;
}
interface LecteurPixels { read(): Promise<{ readonly done: true } | { readonly done: false; readonly value: Uint8Array }>;
  cancel(): Promise<void> }
export interface ReponsePhoto { readonly status: number; readonly headers: { get(nom: string): string | null };
  readonly body: { getReader(): LecteurPixels } | null }
export interface DependancesApercuPreuve {
  readonly courante: () => boolean; readonly urlBase: string; readonly jeton: string; readonly signal: AbortSignal;
  readonly creerTemporaire: (mime: 'image/png' | 'image/jpeg') => Promise<TemporairePreuve>;
  readonly fetchPhoto: (url: string, init: { readonly method: 'POST'; readonly headers: Record<string, string>;
    readonly body: string; readonly signal: AbortSignal; readonly redirect: 'error' }) => Promise<ReponsePhoto>;
}
export type ApercuPreuve = { readonly genre: 'pret'; readonly uri: string; readonly courante: () => boolean;
  readonly purger: () => Promise<void> } | { readonly genre: 'echec'; readonly code: string; readonly status?: number };
const MAX = 10485760;
class ApercuIndisponible extends Error {}
/** Bounded private temporary bytes; readiness never survives a captured authority change. */
export function creerChargeurApercuPreuve(d: DependancesApercuPreuve) {
  return { charger: async (selection: SelectionPhotoPreuve, photo: PhotoPreuveM6): Promise<ApercuPreuve> => {
    let fichier: TemporairePreuve | null = null, lecteur: LecteurPixels | null = null, ferme = false, retenu = false;
    const controller = new AbortController();
    const annuler = () => controller.abort();
    d.signal.addEventListener('abort', annuler, { once: true });
    const minuteur = setTimeout(annuler, 120000);
    const courante = () => d.courante() && !d.signal.aborted && !controller.signal.aborted;
    const garder = () => { if (!courante()) throw new ApercuIndisponible(); };
    try {
      garder();
      if (photo.etat_actuel !== 'disponible' || !Number.isSafeInteger(photo.taille_octets) ||
        photo.taille_octets < 1 || photo.taille_octets > MAX || !/^[a-f0-9]{64}$/.test(photo.empreinte_sha256) ||
        photo.reference !== 'fichier:sha256:' + photo.empreinte_sha256 || selection.position_photo !== photo.position_photo)
        return { genre: 'echec', code: 'photo_indisponible' };
      const base = new URL(d.urlBase);
      if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash)
        return { genre: 'echec', code: 'configuration_invalide' };
      fichier = await d.creerTemporaire(photo.type_mime); garder();
      const response = await d.fetchPhoto(d.urlBase.replace(/\/$/, '') + '/opsys/m6/preuves/photo', {
        method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + d.jeton },
        body: JSON.stringify({ wct_id: selection.wct_id,
          preuve: { index: selection.preuve.index, hash_maillon: selection.preuve.hash_maillon },
          position_photo: selection.position_photo }), signal: controller.signal, redirect: 'error',
      });
      garder();
      if (response.status !== 200) return { genre: 'echec', code: 'photo_refusee', status: response.status };
      const h = response.headers;
      if (h.get('content-type') !== photo.type_mime || h.get('content-length') !== String(photo.taille_octets) ||
        h.get('x-opsys-sha256') !== photo.empreinte_sha256 || h.get('etag') !== '"' + photo.empreinte_sha256 + '"' ||
        (h.get('content-encoding') !== null && h.get('content-encoding') !== 'identity') || !response.body)
        return { genre: 'echec', code: 'photo_integrite_invalide' };
      lecteur = response.body.getReader();
      let taille = 0;
      while (true) {
        garder(); const bloc = await lecteur.read(); garder();
        if (bloc.done) break;
        if (!(bloc.value instanceof Uint8Array) || bloc.value.byteLength === 0 || taille + bloc.value.byteLength > photo.taille_octets ||
          taille + bloc.value.byteLength > MAX) throw new ApercuIndisponible();
        fichier.ecrire(bloc.value); taille += bloc.value.byteLength;
      }
      fichier.fermer(); ferme = true; garder();
      if (taille !== photo.taille_octets || fichier.taille() !== taille) throw new ApercuIndisponible();
      const sha = await fichier.empreinte(); garder();
      if (sha !== photo.empreinte_sha256) throw new ApercuIndisponible();
      const temp = fichier;
      let disponible = true;
      const purger = async () => { disponible = false; temp.supprimer(); };
      retenu = true;
      return { genre: 'pret', uri: temp.uri, courante: () => disponible && courante(), purger };
    } catch { return { genre: 'echec', code: courante() ? 'photo_integrite_invalide' : 'photo_lecture_remplacee' }; }
    finally {
      clearTimeout(minuteur); d.signal.removeEventListener('abort', annuler);
      if (!retenu) {
        controller.abort();
        try { if (!ferme) fichier?.fermer(); }
        finally {
          try { fichier?.supprimer(); }
          finally {
            try { void lecteur?.cancel().catch(() => undefined); }
            catch { /* A broken cancel adapter cannot retain the private file. */ }
          }
        }
      }
    }
  } };
}
