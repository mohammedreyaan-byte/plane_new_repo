import { defineConfig } from "tsdown";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: true,
  platform: "neutral",
  exports: true,
  // The i18n instance loads namespaces with import(`../locales/${language}/${namespace}.json`).
  // Those files must exist next to dist/index.js, otherwise every key renders as its raw id.
  copy: ["src/locales"],
});
