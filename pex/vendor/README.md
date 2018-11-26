PEX Vendored Distributions
==========================

PEX vendors distributions of critical third party code it uses at build-time and at run-time both
to ensure predictable behavior and provide a zero-dependency library and cli tool to build upon
without fear of dependency conflict by higher software layers.

Vendored code is stored in the `_vendored/` directory with re-written self-referential imports but
no other modifications whatsoever. If vendored code needs a fix, please submit patches upstream and
re-vendor when the fix is released.

To update versions of vendored code or add new vendored code:

1. Modify `pex.vendor.iter_vendor_specs` with updated versions or new distributions.
   Today that function looks like:
   ```python
   def iter_vendor_specs(include_wheel=True):
     """Iterate specifications for code vendored by pex.

     :param bool include_wheel: If ``True`` include the vendored wheel spec.
     :return: An iterator over specs of all vendored code optionally including ``wheel``.
     :rtype: :class:`collection.Iterator` of :class:`VendorSpec`
     """
     yield VendorSpec.create('setuptools==40.6.2')
     if include_wheel:
       # We're currently stuck here due to removal of an API we depend on.
       # See: https://github.com/pantsbuild/pex/issues/603
       yield VendorSpec.create('wheel==0.31.1')
   ```
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