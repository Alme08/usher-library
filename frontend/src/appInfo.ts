/**
 * Copy constants for the provisional page.
 *
 * The provisional page is what the user sees while the real product
 * surface (reading, annotations, comments) is not implemented yet.
 * Keeping the copy as exported constants lets us test it without a
 * DOM (RNF-2, RNF-5) and gives later specs a single place to change
 * it.
 *
 * All visible text must be in English (RNF-4, constitution P6).
 */

export const appInfo = {
  name: "Usher Library",
  tagline: "A collaborative reading room for The Fall of the House of Usher.",
} as const;
