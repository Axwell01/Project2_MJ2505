"""
All assumed input parameters for Project 2, in one place.

Every number used by the step scripts is defined here, with its unit and
the source or reasoning behind it. Change a value here and every step that
uses it picks up the change, so the assumptions stay consistent between
steps (as the project description requires).

Units used throughout the project:
    power / heat flow      kW
    energy                 kWh  (1 hour time steps, so kW in one hour = kWh)
    money                  EUR
    pipe length            m
"""

import math

# ---------------------------------------------------------------------------
# General / economic assumptions
# ---------------------------------------------------------------------------
COUNTRY = "Sweden"  # Used for fuel prices (Step 3) and solar profile (Step 3)

# Real discount rate and lifetime used to turn investment costs into a
# yearly cost (annuity). 4 % real is the rate used by the Danish Energy
# Agency technology catalogue for socio-economic calculations.
DISCOUNT_RATE = 0.04        # -
PIPE_LIFETIME = 40          # years, typical lifetime of pre-insulated DH pipes


def annuity_factor(rate, years):
    """Capital recovery factor: yearly cost per EUR invested."""
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


# ---------------------------------------------------------------------------
# Water / temperature assumptions (3rd generation DH, Swedish practice)
# ---------------------------------------------------------------------------
T_SUPPLY = 85.0             # degC, typical Swedish supply temperature
T_RETURN = 45.0             # degC, typical Swedish return temperature
DELTA_T = T_SUPPLY - T_RETURN   # K
RHO_WATER = 970.0           # kg/m3 at ~65 degC (mean temperature)
CP_WATER = 4.19             # kJ/(kg K)

# ---------------------------------------------------------------------------
# Pipe catalogue
# ---------------------------------------------------------------------------
# For each pipe type (DN = nominal diameter in mm):
#   d_inner   inner diameter [m]. Simplification: d_inner = DN.
#   v_max     maximum design flow velocity [m/s]. Small pipes are limited to
#             low velocities to keep the pressure drop around 100-200 Pa/m;
#             larger pipes allow higher velocities (Frederiksen & Werner,
#             "District Heating and Cooling", 2013).
#   invest    investment (construction) cost [EUR/m]. Course DHNx tutorial,
#             discrete_DN_numbers/Case 1/invest_data/network/pipes.csv
#             (column fix_costs). Annualised below with DISCOUNT_RATE and
#             PIPE_LIFETIME, because the objective is a yearly cost.
#   loss_w_m  heat loss per metre of trench [W/m]. Same tutorial file
#             (column l_factor_fix, kW/m). The loss is constant whenever the
#             pipe is built, because the water is hot all year round.
#
# Capacity follows from  P_max = rho * cp * v_max * A * delta_T.
# (The tutorial's own cap_max values are not used: they are not explained
# and are too small for the course demand profiles, e.g. 179 kW for DN-50.)
PIPE_TYPES = {
    # name     DN   v_max  invest  loss_w_m
    "DN-25": (25, 0.80, 466.0, 7.656),
    "DN-32": (32, 1.00, 491.0, 8.6405),
    "DN-40": (40, 1.15, 522.0, 9.5755),
    "DN-50": (50, 1.30, 563.0, 9.141),
    "DN-63": (63, 1.50, 620.0, 11.4125),
}


def pipe_capacity_kw(dn, v_max):
    """Maximum heat the pipe can carry [kW]."""
    area = math.pi * (dn / 1000) ** 2 / 4
    return RHO_WATER * CP_WATER * v_max * area * DELTA_T


def pipe_table(names):
    """
    Rows for DHNx's investment_options/network/pipes.csv.

    DHNx cost model per pipe:  cost = length * (fix_costs + capex_pipes * capacity)
    DHNx loss model per pipe:  loss = length * (l_factor_fix + l_factor * capacity)

    The real cost and loss depend only on which pipe type is built, so they
    go into the fixed parts (fix_costs, l_factor_fix). capex_pipes is a tiny
    number only so that the reported capacity equals the flow actually needed.
    """
    crf = annuity_factor(DISCOUNT_RATE, PIPE_LIFETIME)
    rows = []
    for name in names:
        dn, v_max, invest, loss_w_m = PIPE_TYPES[name]
        rows.append({
            "label_3": name,
            "active": 1,
            "nonconvex": 1,                          # built or not built (binary)
            "l_factor": 0.0,                         # kW/(kW*m)
            "l_factor_fix": loss_w_m / 1000,         # kW/m
            "cap_max": round(pipe_capacity_kw(dn, v_max), 1),  # kW
            "cap_min": 0,                            # kW
            "capex_pipes": 1e-4,                     # EUR/(kW*m*a)
            "fix_costs": round(invest * crf, 3),     # EUR/(m*a)
            # extra columns for the report (ignored by DHNx)
            "invest_eur_per_m": invest,
            "v_max_m_s": v_max,
        })
    return rows


# ---------------------------------------------------------------------------
# Heat producers
# ---------------------------------------------------------------------------
# variable_costs = (fuel price / efficiency + variable O&M)  [EUR/kWh heat]
# Sources:
#   - Wood chips in Sweden ~20-25 EUR/MWh (Energimyndigheten, wood fuel
#     price statistics); boiler efficiency 0.90 and variable O&M ~2 EUR/MWh
#     (Danish Energy Agency, Technology Data for heat generation, wood chip
#     boiler).
#   - Natural gas for heat in Sweden ~50 EUR/MWh incl. energy and CO2 tax is
#     excluded here (CO2 cost is added in Step 5); efficiency 0.97, variable
#     O&M ~1 EUR/MWh (Danish Energy Agency, gas boiler).
# max_kw: the biomass boiler is a base-load unit sized below the peak, so the
# gas boiler is needed for peak hours (common Swedish practice).
PRODUCERS_STEP1 = {
    # id: name, variable cost EUR/kWh, maximum output kW
    "0": {"name": "Biomass boiler (wood chips)",
          "variable_costs": round(22 / 0.90 / 1000 + 0.002, 4),
          "max_kw": 400},
    "1": {"name": "Natural gas boiler",
          "variable_costs": round(50 / 0.97 / 1000 + 0.001, 4),
          "max_kw": 1000},
}
