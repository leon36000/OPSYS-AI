// Config Babel standard Expo : le même préréglage sert au bundler Metro (app native) et,
// via le préréglage jest-expo, aux tests Jest — voir docs.expo.dev/develop/unit-testing.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
  };
};
