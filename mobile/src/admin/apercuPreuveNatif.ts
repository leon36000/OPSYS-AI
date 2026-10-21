import { fetch as fetchExpo } from 'expo/fetch';
import { File, FileMode, Paths } from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import { capturerSessionAdminLecture } from '../protocole/configuration';
import { creerChargeurApercuPreuve } from './apercuPreuve';
import type { SelectionPhotoPreuve, ApercuPreuve } from './apercuPreuve';
import type { PhotoPreuveM6 } from '../m6/preuvesLecture';

/** Real locked Expo adapters; unit mocks do not qualify a phone or native image cache. */
export async function chargerApercuPreuveNatif(selection: SelectionPhotoPreuve, photo: PhotoPreuveM6,
  signal: AbortSignal, encoreCourante: () => boolean): Promise<ApercuPreuve> {
  const capture = capturerSessionAdminLecture(), session = capture.session;
  if (!session || !capture.courante() || !encoreCourante()) return { genre: 'echec', code: 'photo_lecture_remplacee' };
  return creerChargeurApercuPreuve({ urlBase: session.urlBase, jeton: session.jeton, signal,
    courante: () => capture.courante() && encoreCourante(),
    fetchPhoto: (url, init) => fetchExpo(url, init),
    creerTemporaire: async mime => {
      const file = new File(Paths.cache, 'm6-preuve-' + Crypto.randomUUID() + (mime === 'image/png' ? '.png' : '.jpg'));
      file.create({ overwrite: false });
      let handle;
      try { handle = file.open(FileMode.WriteOnly); }
      catch (e) { if (file.exists) file.delete(); throw e; }
      let ferme = false;
      return { uri: file.uri, ecrire: bytes => handle.writeBytes(bytes),
        fermer: () => { if (!ferme) { ferme = true; handle.close(); } }, taille: () => file.size,
        empreinte: async () => {
          if (!file.exists || file.size !== photo.taille_octets || file.size > 10485760) throw new Error('photo_size');
          const bytes = await file.bytes();
          if (bytes.byteLength !== photo.taille_octets) throw new Error('photo_size');
          const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes);
          return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
        }, supprimer: () => { if (file.exists) file.delete(); } };
    },
  }).charger(selection, photo);
}
