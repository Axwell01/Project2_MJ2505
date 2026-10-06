"""
Small compatibility fixes so DHNx 0.0.4 works with oemof.solph 0.6.
Importing this module applies them. They do nothing on versions that do not
need them.
"""

import oemof.solph as solph
from oemof.solph import processing

# 1) DHNx 0.0.4 still uses the old name `Flow.nominal_value` for existing
#    pipes. oemof.solph >= 0.6 renamed it to `nominal_capacity`.
if not hasattr(solph.Flow, "nominal_value"):
    solph.Flow.nominal_value = property(
        lambda self: self.nominal_capacity,
        lambda self, value: setattr(self, "nominal_capacity", value))

# 2) oemof.solph 0.6 computes a "MIP gap" in meta_results(), which crashes
#    when the solver reports no lower bound (CBC on a pure linear problem).
#    The optimisation itself is fine; only this summary number is missing.
_meta_results = processing.meta_results


def _safe_meta_results(om, undefined=False):
    try:
        return _meta_results(om, undefined)
    except TypeError:
        solver = om.es.results["solver"][0]
        return {"objective": om.objective(), "problem": {},
                "solver": {"Termination condition": str(solver["Termination condition"])}}


if getattr(processing.meta_results, "__name__", "") != "_safe_meta_results":
    processing.meta_results = _safe_meta_results
    solph.processing.meta_results = _safe_meta_results
