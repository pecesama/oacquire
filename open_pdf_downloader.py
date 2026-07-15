"""DEPRECATED — this module was renamed to `oacquire` in v2.0.0.

This shim keeps `from open_pdf_downloader import retrieve_pdf` working for one
release cycle. It will be removed in v3.0.0. Please migrate to:

    from oacquire import retrieve_pdf, build_session

and use the `oacquire` console script instead of `python open_pdf_downloader.py`.
"""
import warnings

from oacquire import *          # noqa: F401,F403
from oacquire import __all__    # noqa: F401
from oacquire.cli import main   # noqa: F401

warnings.warn(
    "`open_pdf_downloader` was renamed to `oacquire` in v2.0.0 and this shim "
    "will be removed in v3.0.0. Use `import oacquire` instead.",
    DeprecationWarning,
    stacklevel=2,
)

if __name__ == "__main__":
    raise SystemExit(main())
