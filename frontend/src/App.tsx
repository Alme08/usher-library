import type { JSX } from "react";

import { appInfo } from "./appInfo.ts";

/**
 * Provisional page.
 *
 * The whole point of this component is to prove that the frontend
 * serves something visible in the browser while the real product
 * surface is being built (RF-10). All copy comes from `appInfo` so it
 * stays testable without a DOM (RNF-2, RNF-5) and so the visible text
 * has a single source of truth.
 */
export default function App(): JSX.Element {
  return (
    <main>
      <h1>{appInfo.name}</h1>
      <p>{appInfo.tagline}</p>
    </main>
  );
}
