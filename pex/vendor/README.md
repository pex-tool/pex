PEX Vendored Distributions
==========================

PEX vendors distributions of critical third party code it uses at build-time and at run-time both
to ensure predictable behavior and provide a zero-dependency library and cli tool to build upon
without fear of dependency conflict by higher software layers.

Vendored code is stored in the `_vendored/` directory with re-written self-referential imports but
no other modifications whatsoever. If vendored code needs a fix, please submit patches upstream and
re-vendor when the fix is released.

To update versions of vendored code or add new vendored code:

1. Modify [`pex.vendor.iter_vendor_specs`](./__init__.py#L91) with updated versions or new distributions.
   Simply edit an existing `VendorSpec` or `yield` a new one.
2. Run `tox -e vendor`.
   This will replace all vendored code even if versions have not changed and then rewrite any
   imports in the vendored code that refer back to any other vendored code to use the
   `pex.third_party` importer prefix. In addition, any direct, un-prefixed imports of vendored code
   in the pex codebase will be re-written. This operation is idempotent and can be (re-)run without
   fear.
3. Run tests and, once green, check in the newly vendored code.

After this, and newly vendored distribution can be imported by pex code using the `pex.third_party`
import prefix.
