"""
Helper functions shared by the DHNx steps (Step 1 and Step 2):
reading the demand profiles, writing the DHNx input CSV files, running the
optimisation and summarising the results.
"""

import math
import os
import shutil

import dhnx
import pandas as pd

from src import parameters as par

from src import compat  # noqa: F401  (fixes for DHNx / oemof versions)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMAND_CSV = os.path.join(ROOT, "data", "demand_profiles.csv")
DEMAND_XLSX = os.path.join(ROOT, "data", "Demand_profiles_heating.xlsx")

# Reference point for turning local x/y metres into lat/lon (only used for
# plots). A suburb south of Stockholm.
LAT0, LON0 = 59.25, 18.05


def load_demand():
    """Hourly demand of all 50 profiles [kW], 8760 rows."""
    if not os.path.exists(DEMAND_CSV):
        df = pd.read_excel(DEMAND_XLSX, sheet_name="Sheet1").drop(columns="Time")
        # column 18 has no header in the Excel file
        df = df.rename(columns={"Unnamed: 18": "Load 18"})
        df.index = pd.RangeIndex(1, len(df) + 1, name="hour")
        df.to_csv(DEMAND_CSV)
    return pd.read_csv(DEMAND_CSV, index_col="hour")


def xy_to_latlon(x, y):
    lat = LAT0 + y / 111_320
    lon = LON0 + x / (111_320 * math.cos(math.radians(LAT0)))
    return lat, lon


def write_network(folder, producers, forks, consumers, streets, connections,
                  demand):
    """
    Write a DHNx ThermalNetwork as CSV files.

    producers / forks / consumers: dict id -> (x, y) in metres
    streets:     list of (from fork, to fork)  -> candidate fork-fork pipes
    connections: list of (from, to) node names for producer and house
                 connections, e.g. ("producers-0", "forks-0")
    demand:      DataFrame, one column per consumer id, hourly kW
    """
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(os.path.join(folder, "sequences"))

    def nodes(d):
        rows = []
        for i, (x, y) in d.items():
            lat, lon = xy_to_latlon(x, y)
            rows.append({"id": i, "lat": lat, "lon": lon, "x": x, "y": y})
        return pd.DataFrame(rows).set_index("id")

    tables = {"producers": nodes(producers), "forks": nodes(forks),
              "consumers": nodes(consumers)}
    for name, df in tables.items():
        df.to_csv(os.path.join(folder, name + ".csv"))

    def xy(node):
        kind, i = node.split("-", 1)
        return {"producers": producers, "forks": forks,
                "consumers": consumers}[kind][i]

    pipes = []
    edges = [("forks-" + a, "forks-" + b) for a, b in streets] + connections
    for k, (a, b) in enumerate(edges):
        (x1, y1), (x2, y2) = xy(a), xy(b)
        pipes.append({"id": k, "from_node": a, "to_node": b,
                      "length": round(math.hypot(x2 - x1, y2 - y1), 1)})
    pd.DataFrame(pipes).set_index("id").to_csv(os.path.join(folder, "pipes.csv"))

    seq = demand.copy()
    seq.index = pd.RangeIndex(0, len(seq), name="timestep")
    seq.to_csv(os.path.join(folder, "sequences", "consumers-heat_flow.csv"))


def write_invest_options(folder, pipe_names, producers):
    """
    Write DHNx investment options: which pipe types may be built, and what
    the producers and consumers look like in the oemof model.
    producers: dict id -> {"variable_costs": EUR/kWh, "max_kw": kW}
    """
    if os.path.exists(folder):
        shutil.rmtree(folder)
    for sub in ["network", "consumers", "producers"]:
        os.makedirs(os.path.join(folder, sub))

    pipes = pd.DataFrame(par.pipe_table(pipe_names))
    pipes.drop(columns=["invest_eur_per_m", "v_max_m_s"]).to_csv(
        os.path.join(folder, "network", "pipes.csv"), index=False)

    bus = pd.DataFrame([{"label_2": "heat", "active": 1, "excess": 0,
                         "shortage": 0, "shortage costs": 99999,
                         "excess costs": 99999}])
    bus.to_csv(os.path.join(folder, "consumers", "bus.csv"), index=False)
    bus.to_csv(os.path.join(folder, "producers", "bus.csv"), index=False)

    pd.DataFrame([{"label_2": "heat", "active": 1, "nominal_capacity": 1}]).to_csv(
        os.path.join(folder, "consumers", "demand.csv"), index=False)

    # General source definition; the cost and size of each producer are
    # given per producer in producers.csv (columns heat.source.*).
    pd.DataFrame([{"label_2": "heat", "active": 1, "variable_costs": 0}]).to_csv(
        os.path.join(folder, "producers", "source.csv"), index=False)
    return pipes


def add_producer_attributes(network_folder, producers):
    """Add per-producer cost and size columns that DHNx reads automatically."""
    path = os.path.join(network_folder, "producers.csv")
    df = pd.read_csv(path, index_col="id")
    df.index = df.index.astype(str)
    df["name"] = [producers[i]["name"] for i in df.index]
    df["heat.source.variable_costs"] = [producers[i]["variable_costs"] for i in df.index]
    df["heat.source.nominal_capacity"] = [producers[i]["max_kw"] for i in df.index]
    df.to_csv(path)


def find_solver():
    """Use CBC if installed, otherwise GLPK."""
    if shutil.which("cbc"):
        return "cbc"
    if shutil.which("glpsol"):
        return "glpk"
    raise RuntimeError("No solver found. Install CBC (see README).")


N_DESIGN_HOURS = 12           # 8760 / 12 = 730 h represented by each design hour


def design_hours(demand, n=N_DESIGN_HOURS):
    """
    Pick the hours used to size the pipes: the peak hour of every consumer
    (so every house connection is sized for its own peak) plus the hours with
    the highest total demand (so the main pipes are sized for the coincident
    peak). Returns sorted hour positions (0-based).
    """
    hours = list(dict.fromkeys(int(demand[c].values.argmax()) for c in demand.columns))
    for h in demand.sum(axis=1).values.argsort()[::-1]:
        if len(hours) >= n:
            break
        if int(h) not in hours:
            hours.append(int(h))
    return sorted(hours)


def run_dhnx(network_folder, invest_folder, num_ts, hours_per_step=1.0,
             solver=None):
    """
    Load the CSV inputs and run DHNx's investment optimisation.

    hours_per_step: how many hours of the year each time step represents.
    Costs that occur every hour (heat production, which includes the pipe
    heat losses) are multiplied by this, so the objective is a yearly cost.
    """
    network = dhnx.network.ThermalNetwork(network_folder)
    invest_opt = dhnx.input_output.load_invest_options(invest_folder)
    network.optimize_investment(
        invest_options=invest_opt,
        heat_demand="series",
        num_ts=num_ts,
        frequence=f"{hours_per_step:g}h",
        simultaneity=1,
        bidirectional_pipes=False,
        solver=solver or find_solver(),
        solve_kw={"tee": False},
    )
    return network


def design_then_operate(net_dir, inv_dir, producers, forks, consumers,
                        streets, connections, demand, pipe_names,
                        producer_params):
    """
    Two-stage approach (keeps the problem small enough to solve in seconds):

    1. DESIGN: DHNx chooses the topology and pipe types using the design
       hours only (a mixed-integer problem: build / don't build each pipe
       type on each street).
    2. OPERATION: the chosen pipes are fixed ("existing" pipes in DHNx) and
       the network is run for all 8760 hours (a linear problem) to get the
       hourly producer output, yearly heat losses and operating costs.
    """
    hours = design_hours(demand)
    write_network(net_dir, producers, forks, consumers, streets, connections,
                  demand.iloc[hours])
    add_producer_attributes(net_dir, producer_params)
    pipe_table = write_invest_options(inv_dir, pipe_names, producer_params)
    print(f"Design hours used for pipe sizing: {[h + 1 for h in hours]}")
    print("Solving design problem (which pipes, which types)...")
    design = run_dhnx(net_dir, inv_dir, num_ts=len(hours),
                      hours_per_step=8760 / len(hours))
    built = design.results.optimization["components"]["pipes"]
    built = built[built["capacity"] > 0]

    op_net_dir = net_dir + "_operation"
    op_inv_dir = inv_dir + "_operation"
    write_fixed_network(net_dir, op_net_dir, built, demand)
    write_invest_options(op_inv_dir, pipe_names, producer_params)
    operation_pipe_table(pipe_table).to_csv(
        os.path.join(op_inv_dir, "network", "pipes.csv"), index=False)
    print("Solving operation problem (8760 hours, pipes fixed)...")
    operation = run_dhnx(op_net_dir, op_inv_dir, num_ts=len(demand))
    return design, operation, pipe_table, hours


def operation_pipe_table(pipe_table):
    """
    Pipe types for the operation run. The pipes already exist, so their heat
    loss is a constant (nonconvex = 0). Street pipes between two forks can
    carry heat in either direction depending on the hour, so they are added
    once per direction; each direction gets half of the heat loss ("-half"
    types) so the total loss of the street pipe stays correct.
    """
    full = pipe_table.drop(columns=["invest_eur_per_m", "v_max_m_s"]).copy()
    full["nonconvex"] = 0
    half = full.copy()
    half["label_3"] = half["label_3"] + "-half"
    half["l_factor_fix"] = half["l_factor_fix"] / 2
    return pd.concat([full, half], ignore_index=True)


def write_fixed_network(src_dir, dst_dir, built, demand):
    """Copy the network, keeping only the built pipes, as existing pipes."""
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir)
    rows = []
    for i, p in built.iterrows():
        # small margin so the operation run is never limited by rounding
        cap = p["capacity"] * 1.001 + 0.01
        base = {"length": p["length"], "capacity": cap, "existing": 1}
        if p["from_node"].startswith("forks") and p["to_node"].startswith("forks"):
            rows.append({"from_node": p["from_node"], "to_node": p["to_node"],
                         "hp_type": p["hp_type"] + "-half", **base})
            rows.append({"from_node": p["to_node"], "to_node": p["from_node"],
                         "hp_type": p["hp_type"] + "-half", **base})
        else:
            rows.append({"from_node": p["from_node"], "to_node": p["to_node"],
                         "hp_type": p["hp_type"], **base})
    keep = pd.DataFrame(rows)
    keep.index.name = "id"
    keep.to_csv(os.path.join(dst_dir, "pipes.csv"))
    used = set(keep["from_node"]) | set(keep["to_node"])
    forks = pd.read_csv(os.path.join(dst_dir, "forks.csv"), index_col="id")
    forks = forks[[f"forks-{i}" in used for i in forks.index]]
    forks.to_csv(os.path.join(dst_dir, "forks.csv"))
    seq = demand.copy()
    seq.index = pd.RangeIndex(0, len(seq), name="timestep")
    seq.to_csv(os.path.join(dst_dir, "sequences", "consumers-heat_flow.csv"))


def producer_output(network):
    """Hourly heat output of each producer [kW]."""
    res = network.results.optimization["oemof"]
    out = {}
    for (n1, n2), v in res.items():
        if n2 is not None and n1.label.tag1 == "producers" and n1.label.tag3 == "source":
            pid = n1.label.tag4.split("-", 1)[1]
            out[pid] = v["sequences"]["flow"].values
    return pd.DataFrame(out)


def summarise(design, operation, pipe_table, producers, demand, out_folder):
    """
    Write result tables and return a dict of key numbers.
    Pipe results come from the design run, hourly producer output from the
    operation run (all 8760 hours).
    """
    os.makedirs(out_folder, exist_ok=True)
    pipes = design.results.optimization["components"]["pipes"].copy()
    built = pipes[pipes["capacity"] > 0].copy()
    pt = pipe_table.set_index("label_3")
    built["invest_eur"] = built["length"] * built["hp_type"].map(pt["invest_eur_per_m"])
    built["annual_cost_eur"] = built["costs"]
    built["loss_kw"] = built["losses"]
    built["annual_loss_kwh"] = built["losses"] * 8760
    built["pipe_capacity_max_kw"] = built["hp_type"].map(pt["cap_max"])
    built["utilisation"] = built["capacity"] / built["pipe_capacity_max_kw"]
    cols = ["from_node", "to_node", "length", "hp_type", "capacity",
            "pipe_capacity_max_kw", "utilisation", "invest_eur",
            "annual_cost_eur", "loss_kw", "annual_loss_kwh"]
    built = built[cols].round(3)
    built.to_csv(os.path.join(out_folder, "pipes_built.csv"))
    pipes.to_csv(os.path.join(out_folder, "pipes_all_candidates.csv"))

    prod = producer_output(operation)
    prod.to_csv(os.path.join(out_folder, "producer_output_hourly.csv"))
    prod_summary = pd.DataFrame({
        "name": [producers[i]["name"] for i in prod.columns],
        "heat_kwh": prod.sum().values,
        "peak_kw": prod.max().values,
        "max_kw_allowed": [producers[i]["max_kw"] for i in prod.columns],
        "variable_cost_eur_per_kwh": [producers[i]["variable_costs"] for i in prod.columns],
    }, index=prod.columns)
    prod_summary["operating_cost_eur"] = (prod_summary["heat_kwh"]
                                          * prod_summary["variable_cost_eur_per_kwh"])
    prod_summary.round({"heat_kwh": 1, "peak_kw": 1, "operating_cost_eur": 1}).to_csv(
        os.path.join(out_folder, "producers_summary.csv"))

    by_type = built.groupby("hp_type").agg(
        number=("length", "size"), length_m=("length", "sum"),
        invest_eur=("invest_eur", "sum"), annual_loss_kwh=("annual_loss_kwh", "sum"))
    by_type.round(1).to_csv(os.path.join(out_folder, "pipes_by_type.csv"))

    total_demand = demand.sum().sum()
    total_loss = built["annual_loss_kwh"].sum()
    key = {
        "design_solver_status": str(design.results.optimization["oemof_meta"]["solver"]["Termination condition"]),
        "operation_solver_status": str(operation.results.optimization["oemof_meta"]["solver"]["Termination condition"]),
        "consumer_demand_kwh": total_demand,
        "peak_demand_coincident_kw": demand.sum(axis=1).max(),
        "network_losses_kwh": total_loss,
        "losses_share_of_supply": total_loss / (total_demand + total_loss),
        "heat_produced_kwh": prod.sum().sum(),
        "check_produced_minus_demand_kwh": prod.sum().sum() - total_demand,
        "pipe_investment_eur": built["invest_eur"].sum(),
        "pipe_annual_cost_eur": built["annual_cost_eur"].sum(),
        "operating_cost_eur": prod_summary["operating_cost_eur"].sum(),
        "total_annual_cost_eur": built["annual_cost_eur"].sum() + prod_summary["operating_cost_eur"].sum(),
        "trench_length_m": built["length"].sum(),
        "pipe_types_used": ", ".join(sorted(built["hp_type"].unique())),
    }
    pd.Series(key).to_csv(os.path.join(out_folder, "key_results.csv"), header=["value"])
    return key, built, prod_summary, by_type
