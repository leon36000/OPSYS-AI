/** @type {import('jest').Config} */
module.exports = {
  preset: "jest-expo",
  testPathIgnorePatterns: ["/node_modules/", "/.expo/"],
  // Le préréglage jest-expo ignore la transformation Babel de node_modules SAUF pour une liste
  // fermée de paquets (react-native, expo, ...) — reproduite ici À L'IDENTIQUE (`npx jest
  // --showConfig`, un objet de config ne fusionne pas ses tableaux avec le préréglage) et
  // étendue avec `@noble` : `@noble/curves`/`@noble/hashes` (PLAN T1.4-c3, signature Ed25519 de
  // l'appairage — voir src/appairage/identite.ts) sont publiés en ESM pur, sans build CJS.
  transformIgnorePatterns: [
    "/node_modules/(?!(.pnpm|react-native|@react-native|@react-native-community|expo|@expo|@expo-google-fonts|react-navigation|@react-navigation|@sentry/react-native|native-base|standard-navigation|@noble))",
    "/node_modules/react-native-reanimated/plugin/",
    "/node_modules/@react-native/babel-preset/",
  ],
};
