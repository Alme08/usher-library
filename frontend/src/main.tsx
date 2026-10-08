import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";
import "./index.css";

const container = document.getElementById("root");
if (container === null) {
  // The HTML template always renders the root element; this guard is
  // here to surface a clear error if a future change breaks that
  // invariant instead of crashing inside React.
  throw new Error("Root container #root not found in index.html");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
