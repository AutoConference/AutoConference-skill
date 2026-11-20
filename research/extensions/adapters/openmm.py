"""Bounded CPU reference simulations with OpenMM; never downloads a force field.

Inputs are an explicit small harmonic system in JSON, or a local, already
prepared PDB compatible with OpenMM's bundled Amber14 force field. This is a
reference-simulation subtask, not peptide preparation or a learned propagator.
API: https://docs.openmm.org/latest/userguide/application/02_running_sims.html
"""
from __future__ import annotations

import importlib.metadata
import json
import math
from pathlib import Path

from .common import read_json, safe_input, safe_output


def probe() -> dict:
    try:
        import openmm as mm
        mm.Platform.getPlatformByName("Reference")
        return {"available": True, "reason": "OpenMM CPU Reference platform is available.",
                "versions": {name: importlib.metadata.version(name) for name in ("openmm", "numpy")}}
    except (ImportError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        return {"available": False, "reason": f"OpenMM Reference platform unavailable: {exc}", "versions": {}}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return float(value)


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _vectors(value, count, name, bound):
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{name} must contain one three-vector per particle")
    result = []
    for row in value:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"{name} must contain three-vectors")
        result.append([_number(v, name, -bound, bound) for v in row])
    return result


def validate_system(data: dict) -> dict:
    """Validate the explicit force-field input before importing native code."""
    if not isinstance(data, dict):
        raise ValueError("system input must be an object")
    if set(data) - {"masses_dalton", "positions_nm", "velocities_nm_ps", "bonds"}:
        raise ValueError("system input contains unsupported fields")
    masses = data.get("masses_dalton")
    if not isinstance(masses, list) or not 2 <= len(masses) <= 256:
        raise ValueError("masses_dalton must contain 2 to 256 particle masses")
    masses = [_number(v, "mass", 0.1, 1000) for v in masses]
    positions = _vectors(data.get("positions_nm"), len(masses), "positions_nm", 1000)
    velocities = _vectors(data.get("velocities_nm_ps", [[0, 0, 0] for _ in masses]),
                          len(masses), "velocities_nm_ps", 100)
    bonds = data.get("bonds")
    if not isinstance(bonds, list) or not 1 <= len(bonds) <= 1024:
        raise ValueError("bonds must contain 1 to 1024 [i,j,length_nm,k_kj_mol_nm2] entries")
    checked, seen = [], set()
    for bond in bonds:
        if not isinstance(bond, list) or len(bond) != 4:
            raise ValueError("each bond must be [i,j,length_nm,k_kj_mol_nm2]")
        i = _integer(bond[0], "bond particle i", 0, len(masses) - 1)
        j = _integer(bond[1], "bond particle j", 0, len(masses) - 1)
        if i == j or (min(i, j), max(i, j)) in seen:
            raise ValueError("self bonds and duplicate bonds are not supported")
        if math.dist(positions[i], positions[j]) < 1e-8:
            raise ValueError("bonded particles must not start at coincident positions")
        seen.add((min(i, j), max(i, j)))
        checked.append([i, j, _number(bond[2], "bond length", 0.001, 10),
                        _number(bond[3], "bond stiffness", 0.001, 1e6)])
    return {"masses_dalton": masses, "positions_nm": positions,
            "velocities_nm_ps": velocities, "bonds": checked}


def run(request: dict, workspace: Path) -> dict:
    tier = request.get("tier")
    if type(tier) is not int or tier not in (25, 75, 100):
        raise ValueError("OpenMM run tier must be 25, 75 or 100")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    unknown = set(params) - {"steps", "sample_every", "timestep_ps", "initial_temperature_k", "seed"}
    if unknown:
        raise ValueError(f"unsupported OpenMM parameters: {', '.join(sorted(unknown))}")
    steps = _integer(params.get("steps", 100), "steps", 1, 5000)
    stride = _integer(params.get("sample_every", max(1, math.ceil(steps / 100))), "sample_every", 1, steps)
    if math.ceil(steps / stride) > 500:
        raise ValueError("at most 500 trajectory frames may be retained")
    dt = _number(params.get("timestep_ps", 0.001), "timestep_ps", 0.00001, 0.004)
    temperature = _number(params.get("initial_temperature_k", 0), "initial_temperature_k", 0, 1000)
    seed = _integer(params.get("seed", 17), "seed", 1, 2147483647)
    inputs = request.get("inputs", {})
    if not isinstance(inputs, dict) or set(inputs) not in ({"system"}, {"pdb"}):
        raise ValueError("inputs must contain exactly system (JSON) or pdb (prepared local PDB)")
    explicit = validate_system(read_json(workspace, inputs["system"])) if "system" in inputs else None
    pdb_path = safe_input(workspace, inputs["pdb"]) if "pdb" in inputs else None
    if pdb_path and pdb_path.stat().st_size > 1_000_000:
        raise ValueError("PDB input exceeds the 1 MB small-system limit")

    import numpy as np
    import openmm as mm
    from openmm import unit

    if explicit is not None:
        system = mm.System()
        for mass in explicit["masses_dalton"]:
            system.addParticle(mass * unit.dalton)
        force = mm.HarmonicBondForce()
        for i, j, length, stiffness in explicit["bonds"]:
            force.addBond(i, j, length, stiffness)
        system.addForce(force)
        positions = np.asarray(explicit["positions_nm"], dtype=float)
        velocities = np.asarray(explicit["velocities_nm_ps"], dtype=float)
        masses = np.asarray(explicit["masses_dalton"], dtype=float)
        source = "explicit harmonic bonds; no nonbonded, angle, torsion or solvent forces"
    else:
        from openmm import app
        pdb = app.PDBFile(str(pdb_path))
        if not 2 <= pdb.topology.getNumAtoms() <= 256:
            raise ValueError("prepared PDB must contain 2 to 256 atoms")
        # Only bundled names; user input never chooses a file or URL to load.
        forcefield = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
        system = forcefield.createSystem(pdb.topology, nonbondedMethod=app.NoCutoff, constraints=None)
        positions = np.asarray(pdb.positions.value_in_unit(unit.nanometer), dtype=float)
        masses = np.asarray([system.getParticleMass(i).value_in_unit(unit.dalton)
                             for i in range(system.getNumParticles())], dtype=float)
        velocities = np.zeros_like(positions)
        source = "prepared PDB; bundled Amber14 + TIP3P, NoCutoff, no constraints"

    if tier >= 75 and (math.ceil(steps / stride) + 1) * len(masses) * 3 > 60000:
        raise ValueError("trajectory output exceeds 60000 coordinates; increase sample_every")

    def simulate(timestep, n_steps, record_stride):
        integrator = mm.VerletIntegrator(timestep * unit.picoseconds)
        context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
        try:
            context.setPositions(positions * unit.nanometer)
            if temperature:
                context.setVelocitiesToTemperature(temperature * unit.kelvin, seed)
            else:
                context.setVelocities(velocities * unit.nanometer / unit.picosecond)
            frames = []
            for step in range(0, n_steps + 1):
                if step == 0 or step == n_steps or step % record_stride == 0:
                    state = context.getState(getPositions=True, getVelocities=True, getEnergy=True,
                                             getForces=(step == 0))
                    xyz = state.getPositions(asNumpy=True).value_in_unit(unit.nanometer)
                    vel = state.getVelocities(asNumpy=True).value_in_unit(unit.nanometer / unit.picosecond)
                    potential = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
                    kinetic = state.getKineticEnergy().value_in_unit(unit.kilojoule_per_mole)
                    values = np.concatenate([xyz.reshape(-1), vel.reshape(-1), [potential, kinetic]])
                    if not np.isfinite(values).all():
                        raise ValueError("OpenMM produced non-finite state; reduce the time step or repair the system")
                    frame = {"step": step, "time_ps": step * timestep,
                             "positions_nm": xyz.tolist(), "potential_kj_mol": float(potential),
                             "kinetic_kj_mol": float(kinetic),
                             "momentum_dalton_nm_ps": (masses[:, None] * vel).sum(axis=0).tolist()}
                    if step == 0:
                        forces = state.getForces(asNumpy=True).value_in_unit(unit.kilojoule_per_mole / unit.nanometer)
                        if not np.isfinite(forces).all():
                            raise ValueError("OpenMM produced non-finite forces")
                        frame["max_force_kj_mol_nm"] = float(np.linalg.norm(forces, axis=1).max())
                    frames.append(frame)
                if step < n_steps:
                    integrator.step(1)
            return frames
        finally:
            del context
            del integrator

    frames = simulate(dt, 0 if tier == 25 else steps, stride)
    initial = frames[0]
    metrics = {"particles": int(len(masses)), "frames": len(frames),
               "initial_potential_kj_mol": initial["potential_kj_mol"],
               "initial_max_force_kj_mol_nm": initial["max_force_kj_mol_nm"]}
    if explicit is not None:
        analytic = sum(0.5 * k * (math.dist(positions[i], positions[j]) - length) ** 2
                       for i, j, length, k in explicit["bonds"])
        metrics["initial_energy_absolute_error_kj_mol"] = abs(initial["potential_kj_mol"] - analytic)
    diagnostics = {}
    if tier >= 75:
        metrics["simulated_time_ps"] = steps * dt
        metrics["final_potential_kj_mol"] = frames[-1]["potential_kj_mol"]
        metrics["endpoint_displacement_rms_nm"] = float(np.sqrt(np.mean((np.asarray(frames[-1]["positions_nm"]) - positions) ** 2)))
    if tier == 100:
        totals = np.asarray([f["potential_kj_mol"] + f["kinetic_kj_mol"] for f in frames])
        momenta = np.asarray([f["momentum_dalton_nm_ps"] for f in frames])
        half = simulate(dt / 2, 2 * steps, 2 * stride)
        metrics["max_energy_drift_kj_mol"] = float(np.max(np.abs(totals - totals[0])))
        metrics["max_momentum_drift_dalton_nm_ps"] = float(np.linalg.norm(momenta - momenta[0], axis=1).max())
        metrics["half_step_endpoint_rms_difference_nm"] = float(np.sqrt(np.mean(
            (np.asarray(frames[-1]["positions_nm"]) - np.asarray(half[-1]["positions_nm"])) ** 2)))
        diagnostics = {"half_step_final_positions_nm": half[-1]["positions_nm"],
                       "comparison": "same physical duration and seed, half integration time step"}
    relative = f"{request.get('_output_dir', 'runs/science-extensions/openmm')}/trajectory.json"
    output = safe_output(workspace, relative)
    output.write_text(json.dumps({"source": source, "integrator": "Verlet (NVE)",
                                 "platform": "Reference", "initial_temperature_k": temperature,
                                 "frames": frames, "diagnostics": diagnostics}, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return {"metrics": metrics, "artifacts": [relative],
            "notes": [source, "Reference CPU only; temperature controls initial velocities, not a thermostat.",
                      "This executes a bounded reference simulation; it does not validate a learned molecular propagator."]}
