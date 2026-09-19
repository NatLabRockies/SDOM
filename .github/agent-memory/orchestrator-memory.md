# Orchestrator Memory

- Marginal prices use a fixed-decision LP: preserve the planning MIP, clone the incumbent model, fix discrete and capacity/investment variables, attach an imported dual suffix, and solve with `appsi_highs`.
- HiGHS imported supply-balance equality duals have the opposite sign of the demand-cost derivative in SDOM; report LMP as the negative raw dual and retain `supply_balance_dual` for audit.
- Zonal congestion components use the lexicographically first area in each connected component as reference; directional `f_upper`/`f_lower` duals support KKT auditing.
- Focused price coverage belongs in output, zonal export, and network-formulation tests, including a demand finite-difference check.
- VRE minimum installed capacity should use optional `MinCapacity` (MW) in CapSolar/CapWind to align with thermal inputs; direct VRE bounds are `MinCapacity / capacity` on `capacity_fraction`, and Infrasys maps it to `min_active_power`.