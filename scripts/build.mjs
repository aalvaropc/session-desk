import { build } from "esbuild";
import { copyFile, mkdir, rm } from "node:fs/promises";
const destination = new URL("../src/session_desk/web/assets/", import.meta.url);
await mkdir(destination, { recursive: true });
for (const filename of ["icons.js", "types.js", "state.js"])
  await rm(new URL(filename, destination), { force: true });
for (const weight of [400, 500, 600]) {
  await copyFile(
    new URL(
      `../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-${weight}-normal.woff2`,
      import.meta.url,
    ),
    new URL(`plex-${weight}.woff2`, destination),
  );
}
await copyFile(
  new URL("../node_modules/@fontsource/ibm-plex-sans/LICENSE", import.meta.url),
  new URL("FONT-LICENSE.txt", destination),
);

await build({
  entryPoints: ["frontend/app.ts"],
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2020",
  legalComments: "none",
  outfile: "src/session_desk/web/assets/app.js",
});

await build({
  entryPoints: ["frontend/state.ts"],
  bundle: true,
  format: "esm",
  target: "es2020",
  legalComments: "none",
  outfile: "tests/.compiled/state.mjs",
});
