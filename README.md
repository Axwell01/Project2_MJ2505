# Project2_MJ2505 – District Heating Network Optimization

KTH MJ2505, Project 2. DHNx (network design) + oemof.solph (energy system).

| Step | Script | Status |
|------|--------|--------|
| 1 – Base network (5 consumers, 2 producers, DN-32/DN-50) | `Project 2/step1_base_network.ipynb` | done |
| 2 – Expansion (10 consumers, 5 producers, 5 pipe types) | – | next |
| 3 – oemof dispatch of the 5 producers | – | |
| 4 – Add DHNx network losses to the oemof demand | – | |
| 5 – CO₂ cost scenarios | – | |

## How to run

Set up the `dhnx_env` conda environment as described in
`DNHx Tutorial/Prerequisites for the DHNx Tutorial.docx`. Then open
`Project 2/step1_base_network.ipynb` in VS Code, select the **Python (dhnx_env)** kernel and
click **Run All** (the optimisation takes ~2–3 minutes).

The notebook writes:
- `inputs/step1/` – the DHNx input CSV files (network + investment options). Open them in Excel to see exactly what the model gets. Note: in `inputs/step1/network/pipes.csv` the fork–fork street pipes have **half** their real length (see "How the optimisation works").
- `results/step1/` – result tables and plots (`network.png`, `producers.png`, `pipes_built.csv`, `key_results.csv`, ...).

**All assumed numbers are in one file: [`src/parameters.py`](src/parameters.py).** Each one has its unit and source next to it. Change a number there and rerun.

## Files

```
data/Demand_profiles_heating.xlsx   original course data (50 hourly profiles)
data/demand_profiles.csv            same data (Sheet1) as CSV, faster to read
DNHx Tutorial/                      course DHNx tutorial; Step 1 uses its network layout
                                    (introduction/twn_data) and pipe costs/losses
                                    (discrete_DN_numbers/Case 1)
src/parameters.py                   ALL assumptions (pipes, temperatures, costs, producers)
src/network_tools.py                writes DHNx inputs, runs DHNx, summarises results
src/plotting.py                     plots
src/compat.py                       two small fixes so DHNx 0.0.4 works with oemof.solph 0.6
Project 2/step1_base_network.ipynb  Step 1 (Jupyter notebook)
```

---

## Step 1 – what the model does

### Inputs and assumptions

What comes from the course and what is our own assumption:

| Input | Source |
|---|---|
| Hourly demand profiles | Course data (`Demand_profiles_heating.xlsx`), unchanged |
| Network layout and pipe lengths | Course DHNx tutorial, `introduction/twn_data` |
| Pipe investment cost and heat loss | Course DHNx tutorial, `discrete_DN_numbers/Case 1` |
| Pipe capacity | Own calculation (see below) |
| Producers, discount rate, temperatures | Own assumptions with literature sources |

**Country:** Sweden (fuel prices; coordinates only used for plots).

**Units:** we assume the Excel profiles are in **kW** (hourly average, so 1 hour × kW = kWh).

**Layout:** the tutorial's "introduction" network: 2 producers, 11 forks in a ring
(F0 → F1 → … → F10 → F0) and 8 house connections. Pipe lengths are the ones given in
the tutorial (10–30 m). Step 1 connects 5 of the 8 houses, spread around the ring.
DHNx chooses which of the ring's streets to build, so it can choose between several routes
(dashed grey lines in `network.png` are candidate pipes that were *not* built).

**Consumers** – Loads 2–6. Most other columns in the Excel file are copies of
Loads 1–6 with a constant added (e.g. Load 8 = Load 2 + 300). Loads 2–6 are the
five different small profiles. Load 1 (2.6 MW peak) is far too large for a DN-50 pipe.

| Consumer | Profile | Tutorial house (fork) | Peak [kW] | Yearly demand [MWh] | Character |
|---|---|---|---|---|---|
| C0 | Load 2 | 0 (F2) | 50 | 150 | small, strong winter peak |
| C1 | Load 3 | 2 (F3) | 273 | 614 | almost flat all year |
| C2 | Load 4 | 4 (F7) | 109 | 176 | small, seasonal |
| C3 | Load 5 | 5 (F8) | 182 | 1045 | flat base + winter peak |
| C4 | Load 6 | 6 (F10) | 258 | 557 | seasonal, ~0 in summer |
| **Total** | | | **625 (coincident)** | **2542** | |

**Producers** (P0 at F0, P1 at F5, as in the tutorial)

| | Technology | Variable cost [€/kWh heat] | Max output [kW] | Basis |
|---|---|---|---|---|
| P0 | Biomass boiler (wood chips) | 0.0264 | 400 | 22 €/MWh fuel / η 0.90 + 2 €/MWh O&M |
| P1 | Natural gas boiler | 0.0525 | 1000 | 50 €/MWh fuel / η 0.97 + 1 €/MWh O&M |

Fuel prices are typical Swedish levels (Energimyndigheten). Efficiencies and O&M come from the Danish Energy Agency technology catalogue. The biomass boiler is a base-load unit sized below the peak, so the gas boiler covers peaks. CO₂ costs are left out on purpose; they are added in Step 5.

**Pipes** (supply/return temperature 85/45 °C, so ΔT = 40 K)

| | Max velocity [m/s] | Capacity [kW] | Investment [€/m] | Annualised [€/(m·a)] | Heat loss [W/m] |
|---|---|---|---|---|---|
| DN-32 | 1.0 | 131 | 491 | 24.8 | 8.6 |
| DN-50 | 1.3 | 415 | 563 | 28.4 | 9.1 |

- Investment cost and heat loss: DHNx tutorial (`fix_costs` and `l_factor_fix`). The tutorial does not give a unit for `fix_costs`; we read it as the investment cost per metre and annualise it with a 4 % real interest rate over 40 years (annuity factor 0.0505), because the objective is a yearly cost.
- Capacity = ρ · c_p · v_max · (π d²/4) · ΔT, with d = DN (simplification) and velocity limits from Frederiksen & Werner (2013). The tutorial's own capacities (e.g. 179 kW for DN-50) are not used: the tutorial does not explain them, and they are too small for the course demand profiles (the two producer pipes could deliver at most ~360 kW, while the smallest five profiles together peak at ~590 kW).
- The task says DN-30; the tutorial catalogue has DN-32, the closest size, so DN-32 is used.

### How the optimisation works (the "design problem")

DHNx builds an oemof.solph model:

- **Decision variables:** for every candidate street and every pipe type, *build it or not* (binary) and *its capacity* [kW]. Also the heat flow in every pipe and from every producer in every time step [kW].
- **Objective:** minimise yearly cost = Σ pipe annuity [€/a] + Σ heat production × variable cost [€/a]. Heat losses must be produced too, so losses cost money.
- **Constraints:**
  - Heat balance at every fork and consumer: what flows in = what flows out + demand.
  - Pipe flow ≤ capacity of the chosen pipe type.
  - Every built pipe loses a fixed heat amount (W/m × length).
  - Producer output ≤ its maximum.
  - **At most one pipe type per street, usable in both directions** (added by us, see below).

**One pipe per street (our addition to DHNx).** DHNx models a street pipe as two one-way pipes, each with its own build decision and full cost. Left alone, the optimiser can build e.g. DN-50 eastwards and DN-32 westwards on the same street (two pipes in one trench), and DHNx then fails to read the result. We add a constraint: on each street at most one pipe type is built, and it is built in both directions or not at all. Each direction gets half the street length, so the pair costs and loses exactly one pipe's worth. The heat can then flow either way in different hours, like in a real pipe. (See `_one_pipe_per_edge` in `src/network_tools.py`.)

**Two stages, so it solves in minutes rather than hours:**
1. **Design:** the network and pipe types are chosen using 12 *design hours*: each consumer's own peak hour, plus the hours with the highest total demand. Each design hour represents 730 h of the year.
2. **Operation:** the chosen pipes are fixed (each can carry up to its type's capacity) and the network is run for all 8760 hours. This gives the yearly losses, producer output and costs.

Solving all 8760 hours together with the build/don't-build decisions was tried. It had not finished after 10 minutes.

### Results

![network](results/step1/network.png)

| | DN-32 | DN-50 | Total |
|---|---|---|---|
| Number of pipes | 4 | 13 | 17 |
| Length [m] | 80 | 200 | 280 |
| Investment [€] | 39 280 | 112 600 | 151 880 |
| Heat loss [MWh/a] | 6.1 | 16.0 | 22.1 |

| Key number | Value |
|---|---|
| Consumer demand | 2 542 MWh/a |
| Network heat losses | 22 MWh/a (0.9 % of heat supplied) |
| Biomass boiler | 2 486 MWh/a, peak 400 kW (at its limit) |
| Gas boiler | 78 MWh/a, peak 227 kW |
| Pipe annuity | 7 680 €/a |
| Operating cost | 69 740 €/a |
| Total yearly cost | 77 420 €/a |

![producers](results/step1/producers.png)

### Answers to the Step 1 questions (draft, check and rewrite in your own words)

**How does the optimizer decide which pipe type to use?**
For each street it picks the *cheapest pipe type that can still carry the largest flow that street needs*. "Cheapest" means pipe annuity plus the cost of producing the heat the pipe loses. DN-32 is cheaper on both counts: 24.8 vs 28.4 €/(m·a) to build, and 8.6 vs 9.1 W/m lost. So DN-32 is chosen wherever the flow stays below 131 kW, and DN-50 only where the flow is larger.

**Difference between the pipes (cost, losses, capacity)?**
DN-50 carries 3.2× more heat (415 vs 131 kW) but costs only 15 % more per metre and loses 6 % more heat. Per kW of capacity, the big pipe is much cheaper, but you pay for its full cost even when the flow is small.

**Why one type near the beginning of the network and another elsewhere?**
Near the producers, the pipes carry the heat for *many* consumers added together: 400 kW out of the biomass plant (P0 → F0, and F0 → F10 at 96 % of the DN-50 capacity). Only DN-50 can carry that. At the ends of the network, a pipe only serves one house. C0 (51 kW) and C2 (109 kW) fit in DN-32, so DN-32 is used for their connections, and for the street F5 → F6 → F7 that only feeds C2. C1, C3 and C4 have peaks above 131 kW, so even their house connections need DN-50.

**Topology:** the optimizer built a *branched* (tree) network and skipped one street of the ring (F7–F8, 30 m). A closed ring would give redundancy, but every extra metre costs money and loses heat. The optimizer only minimises cost, so it doesn't value reliability. Because street pipes can carry heat in either direction, the biomass plant can still reach every house in low-demand hours, and the gas boiler helps from the other end at peak.

**Model limitations to mention:** fixed ΔT and velocity limits (no detailed hydraulics or pressure drop), d = DN simplification, heat loss independent of the actual flow, pipe sizes chosen on 12 design hours (verified afterwards over all 8760 hours), and the tutorial's pipe lengths do not always match the distance between its node coordinates (we use the given lengths).
