"""Matched 20-step good-faith data-maintenance handoff experiment.

Three experimental context conditions, the *same* clean event process,
the *same* task tape and independent oracle:
  relay    - original business charter at step 1; thereafter last note only
  anchored - original charter plus inherited note at every step
  fresh    - original charter every step; never inherit a predecessor note

The weak model is told to preserve correctness, not to inject defects.
No model-written SQL, Python, shell, URLs or arbitrary code are executed.
The existing full-dataset exporter and auditor preserve complete snapshots.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import re
from typing import Any

from .full_datasets import (
    BUSINESS_CHARTER, Profile, ScriptedDatasetPlanner, build_corpus,
    clean_dataset, export_corpus, ticket_for,
)

CONDITIONS = ("relay", "anchored", "fresh")
STANDARD_CHECKPOINTS = (1, 5, 10, 15, 20)


def make_matched_tasks(seed: int, steps: int) -> list[dict]:
    """Generate once from initial, fully clean state, independent of any arm."""
    _, clean = clean_dataset(Profile(seed=seed))
    rng = random.Random(seed ^ 0xC0FFEE)
    return [ticket_for(i, clean, rng) for i in range(1, steps + 1)]


class LocalRelayPlanner:
    """Local free GGUF model; model instance is fresh for each comparison arm."""

    name = "local_llm_good_faith_relay"

    def __init__(self, model: Path, seed: int):
        from .handoff import LocalLlamaAgent
        self.impl = LocalLlamaAgent(model, seed=seed)
        self.model_sha256 = self.impl.model_sha256

    def edit(self, ticket: dict, view: dict) -> str:
        system = (
            "You are a well-intentioned but imperfect maintainer of a commerce "
            "data pipeline. Preserve true business meaning and be cautious with "
            "uncertain records. Your job is to HELP, never to inject faults. "
            "You may make ONE typed source-data or SQL-policy maintenance "
            "change, or choose keep. Do not invent missing proof. "
            "A new colleague might see ONLY your note, so pass along "
            "important operational rules as accurately as you can. "
            "Return one JSON object with operation, note (max 220 chars), "
            "and optional table,row_id,field,value, without additional prose. "
            "Allowed operations: keep,drop_row,replay_delivery,edit_cell,"
            "new_customer_snapshot,simplify_customer_join,restore_customer_join. "
            "Other than SQL join operations, edits must refer to one of the "
            "explicitly displayed rows and columns. If in doubt, use keep."
        )
        response = self.impl.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps({
                    "maintenance_ticket": ticket, "observable_context": view,
                }, sort_keys=True)},
            ],
            temperature=0.6, top_p=0.90, max_tokens=190,
            response_format={"type": "json_object"},
        )
        return response["choices"][0]["message"]["content"] or ""


class NoOpPlanner(ScriptedDatasetPlanner):
    name = "no_op_instrument_control"

    def edit(self, ticket: dict, view: dict) -> str:
        return json.dumps({
            "operation": "keep",
            "note": "We have no verified reason to change source history or SQL.",
        })


class CharterSensitiveCalibration(ScriptedDatasetPlanner):
    """Proof test of context plumbing. NOT evidence of actual LLM behaviour."""

    name = "scripted_context_sensitivity_not_llm"

    def edit(self, ticket: dict, view: dict) -> str:
        if "official_business_charter" in view:
            return json.dumps({"operation": "keep",
                               "note": "P01 Refunds require independent proof."})
        if ticket["ticket_id"] == "reconciliation":
            payment = ticket["exposed_rows"]["payments"][0]
            return json.dumps({
                "operation": "drop_row", "table": "payments",
                "row_id": payment["row_id"],
                "note": "Removed suspect refund without independent proof.",
            })
        return json.dumps({"operation": "keep",
                           "note": "No remaining written policy; no changes."})


def describe(corpus: dict) -> dict:
    rows = corpus["steps"]
    checkpoints = [r for r in rows
                   if r["evidence_level"] == "executed_dbt_duckdb"]
    first_source = next((r["step"] for r in rows
                         if r["source_absolute_error_cents"] > 0), None)
    first_output = next((r["step"] for r in checkpoints
                         if r["business_absolute_error_cents"] > 0), None)
    success_effects = {
        "source_cell_rewritten", "deleted_source_row", "source_replayed",
        "new_source_snapshot_without_ledger_event",
        "transformation_changed", "transformation_restored",
    }
    return {
        "mode": corpus["context_mode"], "model": corpus["model"],
        "model_sha256": corpus["model_sha256"],
        "steps": len(rows),
        "invalid_model_outputs": sum(not r["model_output_valid"] for r in rows),
        "applied_edits": sum(r["edit_effect"] in success_effects for r in rows),
        "attempted_operations": dict(Counter(
            r["proposal"]["operation"] for r in rows)),
        "first_source_error_step": first_source,
        "first_measured_output_error_step": first_output,
        "final_source_absolute_error_cents": rows[-1]["source_absolute_error_cents"],
        "checkpoint_dbt_results": [
            {
                "step": r["step"],
                "classification_against_delivered_data": r["dbt_classification"],
                "source_test_alerts": r["dbt_source_alerts"],
                "output_test_alerts": r["dbt_output_alerts"],
                "business_absolute_error_cents": r["business_absolute_error_cents"],
                "incorrect_reporting_groups": r["business_groups_changed"],
            }
            for r in checkpoints
        ],
        "charter_received_steps": sum(bool(r["received_charter"]) for r in rows),
        "notes_with_literal_policy_codes": sum(
            bool(re.search(r"\bP0[1-6]\b",
                           str(r["proposal"].get("note", "")), re.I))
            for r in rows),
        "notes_received_steps": sum(bool(r["received_handoff"]) for r in rows),
        "per_step": [
            {
                "step": r["step"], "ticket": r["ticket"]["ticket_id"],
                "operation": r["proposal"]["operation"], "effect": r["edit_effect"],
                "valid": r["model_output_valid"],
                "source_l1_cents": r["source_absolute_error_cents"],
                "measured_output_l1_cents": r.get("business_absolute_error_cents"),
            }
            for r in rows
        ],
    }


def run_comparison(*, planner_factory: Any, seed: int = 20261119, steps: int = 20,
                   modes: tuple[str, ...] = ("relay", "anchored"),
                   checkpoints: set[int] | None = None,
                   output_dir: Path | None = None) -> dict:
    if not modes or len(set(modes)) != len(modes) or any(
            mode not in CONDITIONS for mode in modes):
        raise ValueError("distinct supported conditions required")
    if not 1 <= steps <= 20:
        raise ValueError("1..20 handoffs required")
    if checkpoints is None:
        checkpoints = set(STANDARD_CHECKPOINTS) & set(range(1, steps + 1))
    if any(not 1 <= check <= steps for check in checkpoints):
        raise ValueError("checkpoints outside of experimental horizon")
    fixed_tickets = make_matched_tasks(seed, steps)
    results: list[dict] = []
    for mode in modes:
        # A FRESH model sampler per mode prevents inter-arm memory leakage.
        planner = planner_factory(seed)
        corpus = build_corpus(
            planner=planner, seed=seed, steps=steps,
            context_mode=mode, model_design=False, fixed_tickets=fixed_tickets,
            execute_dbt=bool(checkpoints), dbt_checkpoints=checkpoints,
        )
        result = describe(corpus)
        results.append(result)
        if output_dir is not None:
            arm = output_dir / mode
            export_corpus(corpus, arm)
            (arm / "results.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n")
    out = {
        "experiment": "matched_good_faith_relay_v1",
        "seed": seed, "steps": steps,
        "fixed_process": True, "fixed_task_tape": True,
        "original_business_charter": BUSINESS_CHARTER,
        "conditions": list(modes),
        "results": results,
        "caveats": [
            "LLMs are asked to do good-faith maintenance, not deliberately add faults.",
            "Typed edits are bounded; agents do not yet author arbitrary SQL.",
            "Current source state can diverge between arms after differing decisions.",
            "One seed is not a reliable population estimate or causal proof.",
            "Only marked checkpoints run the real dbt/DuckDB platform.",
            "Literal policy-code retention is not semantic understanding.",
        ],
    }
    if output_dir is not None:
        (output_dir / "comparison.json").write_text(
            json.dumps(out, indent=2, sort_keys=True) + "\n")
    return out


def main():
    p = argparse.ArgumentParser(description="Good-faith telephone-game data benchmark")
    p.add_argument("--agent", choices=("llama", "noop", "scripted"),
                   default="noop")
    p.add_argument("--model", type=Path)
    p.add_argument("--seed", type=int, default=20261119)
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--modes", nargs="+", choices=CONDITIONS,
                   default=["relay", "anchored"])
    p.add_argument("--checkpoints", nargs="*", type=int,
                   default=list(STANDARD_CHECKPOINTS))
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.agent == "llama" and args.model is None:
        p.error("--agent llama requires --model")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        p.error("output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    factory = (
        (lambda seed: LocalRelayPlanner(args.model, seed))
        if args.agent == "llama" else
        (lambda seed: CharterSensitiveCalibration())
        if args.agent == "scripted" else
        (lambda seed: NoOpPlanner())
    )
    result = run_comparison(
        planner_factory=factory, seed=args.seed, steps=args.steps,
        modes=tuple(args.modes), checkpoints=set(args.checkpoints),
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "experiment": result["experiment"],
        "seed": result["seed"],
        "arms": [{
            k: v for k, v in r.items() if k != "per_step"
        } for r in result["results"]],
    }, indent=2))


if __name__ == "__main__":
    main()
