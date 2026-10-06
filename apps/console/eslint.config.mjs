// Flat config, run by `eslint .`. `next lint` was deprecated in Next 15 and is gone in
// 16. Under 15, with no ESLint installed, it dropped into an interactive setup prompt
// and hung, so the lint script had been passing as a no op rather than linting anything.
//
// This is eslint-config-next 16 written out without its Next.js plugin. That plugin
// pins fast-glob 3.3.1, whose brace expansion carries a high advisory with no fixed
// release (GHSA-vfj7-8cjw-p6xm). Enabled, its 22 rules reported nothing here: one
// page, no links between pages, no images, no scripts, no fonts. Every other rule
// matches the official config. Go back to eslint-config-next once a release of the
// plugin drops that dependency.
import { defineConfig, globalIgnores } from "eslint/config";
import importPlugin from "eslint-plugin-import";
import jsxA11y from "eslint-plugin-jsx-a11y";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores([".next/**", "next-env.d.ts", "public/**"]),
  {
    files: ["**/*.{js,jsx,mjs,ts,tsx,mts,cts}"],
    plugins: { react, "react-hooks": reactHooks, import: importPlugin, "jsx-a11y": jsxA11y },
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    settings: { react: { version: "detect" } },
    rules: {
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "import/no-anonymous-default-export": "warn",
      "react/no-unknown-property": "off",
      "react/react-in-jsx-scope": "off",
      "react/prop-types": "off",
      "react/jsx-no-target-blank": "off",
      "jsx-a11y/alt-text": ["warn", { elements: ["img"], img: ["Image"] }],
      "jsx-a11y/aria-props": "warn",
      "jsx-a11y/aria-proptypes": "warn",
      "jsx-a11y/aria-unsupported-elements": "warn",
      "jsx-a11y/role-has-required-aria-props": "warn",
      "jsx-a11y/role-supports-aria-props": "warn",
    },
  },
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": "warn",
      "@typescript-eslint/no-unused-expressions": "warn",
      // The TypeScript conventions for this console forbid `any` without a comment
      // on the adjacent line explaining why the type cannot be expressed. The rule
      // cannot read the comment, so it errors and the comment justifies the disable.
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
]);
