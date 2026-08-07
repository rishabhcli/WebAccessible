import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import App from "./App";
import "./styles.css";

const root = document.getElementById("root");

if (!root) throw new Error("WebAccessible could not find its application root.");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
