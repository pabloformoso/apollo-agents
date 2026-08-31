// ESLint flat config for Next 16. Replaces the deprecated `next lint`
// command (removed in Next 16) with a plain `eslint .` invocation that
// composes the configs eslint-config-next ships as ready-made flat-config
// arrays.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  // Global ignores — must come first to apply to every later config block.
  {
    ignores: [
      ".next/**",
      ".next-e2e/**",
      "out/**",
      "build/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      "playwright/.cache/**",
      "coverage/**",
      "next-env.d.ts",
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    // Project-wide rule overrides.
    rules: {
      // Allow `_`-prefixed args/vars/destructure rest as intentionally unused —
      // standard convention used across the codebase (e.g. positional params
      // we don't need but must declare to satisfy a signature).
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
      // §11 S3 — Strudel must never be bundled. Its dist resolves its own
      // AudioWorklet asset against `import.meta.url`, so it has to be served
      // as a file with its `assets/` neighbour intact; a bundled copy 404s
      // that asset and every AudioWorkletNode then throws, silently, forever.
      // `lib/strudel.ts` loads it by URL through an import the bundler cannot
      // see. A static import here would quietly undo that, so it is an error.
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@strudel/*"],
              message:
                "Do not import @strudel/* — it must not be bundled. Use lib/strudel.ts, which loads it from /vendor/strudel/. See web/CLAUDE.md.",
            },
          ],
        },
      ],
    },
  },
];

export default config;
