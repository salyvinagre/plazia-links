# Upstream baseline

Plazia Links is a fork of PythonPlumber/zly. The upstream MIT license and
copyright notice are retained in LICENSE.

## Initial integration

- Upstream application baseline: `master` at
  `85968e6b50b325c14fa91fb0b583558ecdb7527a` (2026-09-11).
- Original fork main: `a80bffba1fb3b70648fc902d029dbf1af3e52b3e`.
- Integration merge: `f8600f44b28901ab9b095d3648c06fdca8fd53c7`.

Upstream main and master have unrelated Git roots. The integration commit
retains both parents and adopts the master application tree; no local Plazia
code changes existed on main. This is not a squash or a history replacement.

## Product cutover

The organization pool implementation replaces the inherited ORM, legacy auth, workspace and marketing runtime. Upstream history and the MIT notice remain in Git and LICENSE. See ARCHITECTURE.md for the current runtime.
