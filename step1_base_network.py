"""
STEP 1 - Base district heating network (DHNx)

5 consumers, 2 heat producers, 2 pipe types (DN-30 and DN-50).

We give DHNx a set of *candidate* pipes along the streets (including a loop,
so there is more than one possible route). DHNx then decides
  - which candidate pipes to build (the network topology), and
  - which pipe type each built pipe gets,
so that the yearly cost (pipe annuities + heat production cost, including
the heat lost in the pipes) is as low as possible.

The pipes are sized on 12 "design hours" (each consumer's peak hour plus the
hours with the highest total demand). The chosen network is then run for all
8760 hours to get the yearly heat losses, producer output and costs.
See src/network_tools.py -> design_then_operate() for details.

Run:  python step1_base_network.py
Inputs written to:   inputs/step1/
Results written to:  results/step1/
"""

import os

import pandas as pd

from src import network_tools as nt
from src import parameters as par
from src import plotting

STEP = "step1"
NET_DIR = os.path.join(nt.ROOT, "inputs", STEP, "network")
INV_DIR = os.path.join(nt.ROOT, "inputs", STEP, "investment_options")
OUT_DIR = os.path.join(nt.ROOT, "results", STEP)

PIPES = ["DN-30", "DN-50"]
PRODUCERS = par.PRODUCERS_STEP1

# Which demand profiles (columns in the Excel file) the consumers use.
# Loads 2-6 are the five distinct small profiles in the dataset (most other
# columns are copies of these with a constant added). Load 1 is left out
# because its 2.6 MW peak is far above what a DN-50 pipe can carry.
CONSUMER_PROFILES = {
    "0": "Load 2",   # small building, strong winter peak (50 kW peak)
    "1": "Load 3",   # fairly flat demand all year (273 kW peak)
    "2": "Load 4",   # small building, seasonal (109 kW peak)
    "3": "Load 5",   # flat base load + winter peak (182 kW peak)
    "4": "Load 6",   # seasonal, zero in some summer hours (258 kW peak)
}

# ---------------------------------------------------------------------------
# Locations [m] (local x/y). A small street grid with two parallel streets
# joined by two cross streets, so the network can form a loop.
# ---------------------------------------------------------------------------
PRODUCER_XY = {"0": (-80, 0),      # biomass plant, west end
               "1": (580, 150)}    # gas boiler, east end
FORK_XY = {"0": (0, 0), "1": (150, 0), "2": (300, 0), "3": (450, 0),
           "4": (150, 150), "5": (300, 150), "6": (450, 150)}
CONSUMER_XY = {"0": (150, -70), "1": (300, -70), "2": (450, -70),
               "3": (150, 220), "4": (300, 220)}

# Candidate street pipes between forks (DHNx chooses which to build)
STREETS = [("0", "1"), ("1", "2"), ("2", "3"),     # south street
           ("4", "5"), ("5", "6"),                 # north street
           ("1", "4"), ("3", "6"),                 # cross streets
           ("0", "4")]                             # diagonal footpath
CONNECTIONS = [("producers-0", "forks-0"), ("producers-1", "forks-6"),
               ("forks-1", "consumers-0"), ("forks-2", "consumers-1"),
               ("forks-3", "consumers-2"), ("forks-4", "consumers-3"),
               ("forks-5", "consumers-4")]


def main():
    demand_all = nt.load_demand()
    demand = pd.DataFrame({cid: demand_all[col].values
                           for cid, col in CONSUMER_PROFILES.items()})

    design, operation, pipe_table, hours = nt.design_then_operate(
        NET_DIR, INV_DIR, PRODUCER_XY, FORK_XY, CONSUMER_XY, STREETS,
        CONNECTIONS, demand, PIPES, PRODUCERS)
    print("\nPipe types offered to the optimiser:")
    print(pipe_table[["label_3", "cap_max", "invest_eur_per_m", "fix_costs",
                      "l_factor_fix"]].to_string(index=False))

    key, built, prod_summary, by_type = nt.summarise(
        design, operation, pipe_table, PRODUCERS, demand, OUT_DIR)

    names = {"producers": {i: p["name"] for i, p in PRODUCERS.items()},
             "consumers": CONSUMER_PROFILES}
    candidates = pd.read_csv(os.path.join(NET_DIR, "pipes.csv"))
    plotting.plot_network(PRODUCER_XY, FORK_XY, CONSUMER_XY, candidates, built,
                          names, "Step 1 - optimised network",
                          os.path.join(OUT_DIR, "network.png"))
    prod = pd.read_csv(os.path.join(OUT_DIR, "producer_output_hourly.csv"), index_col=0)
    prod.columns = prod.columns.astype(str)
    plotting.plot_producers(prod, names["producers"], demand.sum(axis=1),
                            "Step 1 - heat supplied by each producer",
                            os.path.join(OUT_DIR, "producers.png"))

    print("\nBuilt pipes:")
    print(built.to_string())
    print("\nPipes by type:")
    print(by_type.to_string())
    print("\nProducers:")
    print(prod_summary.to_string())
    print("\nKey results:")
    for k, v in key.items():
        print(f"  {k}: {v:,.3f}" if isinstance(v, float) else f"  {k}: {v}")
    if set(PIPES) - set(built["hp_type"]):
        print("\nWARNING: not all pipe types are used:", set(PIPES) - set(built["hp_type"]))
    print(f"\nResults written to {OUT_DIR}")


if __name__ == "__main__":
    main()
