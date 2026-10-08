/**
 * Tests for the copy constants of the provisional page.
 *
 * These tests must NOT depend on the DOM: the frontend test runner is the
 * native `node --test` (RNF-5, plan §5.3), which does not provide a DOM
 * environment. The contract verified here is the copy contract from
 * `appInfo.ts` only.
 *
 * Covered requirements:
 *  - RF-10: provisional page is served.
 *  - RNF-4: visible copy is in English (ASCII printable, non-empty).
 *  - RNF-5: tests run with the stack's own runner (`node --test`).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { appInfo } from "./appInfo.ts";

/** ASCII printable range, space (0x20) through tilde (0x7E). */
const ASCII_PRINTABLE = /^[\x20-\x7E]+$/;

test("appInfo is an object with the required keys", () => {
  assert.equal(typeof appInfo, "object");
  assert.notEqual(appInfo, null);
  assert.ok("name" in appInfo, "appInfo must expose a 'name' field");
  assert.ok("tagline" in appInfo, "appInfo must expose a 'tagline' field");
});

test("appInfo.name is a non-empty ASCII printable string", () => {
  const { name } = appInfo;
  assert.equal(typeof name, "string");
  assert.ok(name.length > 0, "name must not be empty");
  assert.match(name, ASCII_PRINTABLE, "name must be ASCII printable (English copy, RNF-4)");
});

test("appInfo.tagline is a non-empty ASCII printable string", () => {
  const { tagline } = appInfo;
  assert.equal(typeof tagline, "string");
  assert.ok(tagline.length > 0, "tagline must not be empty");
  assert.match(tagline, ASCII_PRINTABLE, "tagline must be ASCII printable (English copy, RNF-4)");
});
