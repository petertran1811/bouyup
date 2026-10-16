# Lenis 1.3.26 — local browser bundle

Upstream: https://github.com/darkroomengineering/lenis

Source: the workspace read-only reference clone at .omc/research/design/refs/darkroomengineering__lenis, whose root package.json declares version 1.3.26. MIT license is preserved in LICENSE. The requested 1.3.11 artifact could not be downloaded because DNS was unavailable; this folder names the actual source version.

Packaging used an independently written Node 24 script with the built-in node:module stripTypeScriptTypes(source, {mode: 'transform'}) parser. It read source text only: no cloned script, build command, install hook, or source module was executed. TypeScript types were removed and parameter properties converted to JavaScript. Named imports were changed to references into a local modules map; each source module was enclosed in an IIFE in dependency order (maths, debounce, animate, emitter, dimensions, virtual-scroll, lenis). Named exports became the returned module object. The package.json version import became the literal 1.3.26. The final class is exposed as window.Lenis. No application behavior was modified.

lenis.css and LICENSE were copied unchanged. Source comments are retained. The browser artifact requires no runtime CDN or build. Included only on the marketing homepage; BU.motion manages animation frames and destroys Lenis while hidden or under reduced motion.

Validation: node --check lenis.js (syntax only).

Source SHA-256 values:

```
maths.ts: 712a3e31387bd009e2f05d19471bc3dcd60e85f883e2e2f408600d2b85424944
debounce.ts: ee64ae2145eff5779c2472157f336cb37c09cb6af4920446348667e1627f6f06
animate.ts: 0fd6792a79338fe803c413a3c45bebc94e24895a4c6b60429ea6f9bb89930d87
emitter.ts: f09bb2fc0736561b43ebb268a33df9b38b5c9ff004b2c4146d27745f987e2d7f
dimensions.ts: f797db8a23bbacf0677379fbb5dabe991409b90a00a65d4098284198abf198a8
virtual-scroll.ts: 73de46cbd1ac882786903a544d446b137a5a8e1044b29ae558873b271cb94e12
lenis.ts: fda398b7ba2548b26715539bc017c4257eb2eceadb2705c17ee6912b0d5a1b52
```
