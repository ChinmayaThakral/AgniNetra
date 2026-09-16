// Flat config. `next lint` is deprecated in Next 15 and, with no ESLint installed,
// it dropped into an interactive setup prompt and hung, so the lint script has been
// passing as a no op rather than linting anything.
import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // The TypeScript conventions for this console forbid `any` without a comment
      // on the adjacent line explaining why the type cannot be expressed. The rule
      // cannot read the comment, so it errors and the comment justifies the disable.
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
];

export default config;
