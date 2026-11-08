"use client";

import { AllCommunityModule, ModuleRegistry, colorSchemeDarkBlue, themeQuartz } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

export const gridTheme = themeQuartz.withPart(colorSchemeDarkBlue).withParams({
  accentColor: "#38bdf8",
  backgroundColor: "#0b1220",
  headerBackgroundColor: "#0f1729",
  borderColor: "#22314f",
  fontFamily: "var(--font-sans), system-ui, sans-serif",
  fontSize: 13,
});
