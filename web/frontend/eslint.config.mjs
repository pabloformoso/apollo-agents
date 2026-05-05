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
      // The `react-hooks` v7 plugin (shipped with eslint-config-next 16) adds
      // two stylistic rules — `set-state-in-effect` and `refs` — that flag
      // long-standing patterns in this codebase as errors. They are advisory
      // suggestions about effect ergonomics, not bugs; refactoring every
      // existing call site is out of scope for the v2.2.x cleanup PR. Disable
      // here and revisit when we do a dedicated React hooks pass.
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
    },
  },
];

export default config;
