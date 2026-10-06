---
"ocean": minor
---

Read `OCEAN_*` environment variables, with the older `ATLAS_*` names still honored for one release; child processes and generated shims receive both names. `ocean setup` from a checkout now installs an `ocean` command wrapper alongside `atlas`, and the doctor reports either one when missing.
