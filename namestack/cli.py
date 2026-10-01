"""namestack CLI: seed words -> generate -> check -> filter -> report."""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from .checker import AvailabilityChecker, CheckResult, Status
from .generator import Candidate, generate
from .trademark import TrademarkRisk, TrademarkResult, check_words

app = typer.Typer(add_completion=False, no_args_is_help=True, name="namestack")
console = Console()
console_err = Console(stderr=True)

_STATUS_STYLE: dict[Status, tuple[str, str]] = {
    Status.AVAILABLE: ("green", "AVAILABLE"),
    Status.REGISTERED: ("red", "REGISTERED"),
    Status.RATE_LIMITED: ("yellow", "RATE_LIMITED"),
    Status.UNKNOWN: ("grey62", "UNKNOWN"),
}

_STATUS_ORDER: dict[Status, int] = {
    Status.AVAILABLE: 0,
    Status.RATE_LIMITED: 1,
    Status.UNKNOWN: 2,
    Status.REGISTERED: 3,
}

_TM_STYLE: dict[TrademarkRisk, tuple[str, str]] = {
    TrademarkRisk.NONE: ("green", "clear"),
    TrademarkRisk.LOW: ("cyan", "LOW"),
    TrademarkRisk.MEDIUM: ("yellow", "MED"),
    TrademarkRisk.HIGH: ("red", "HIGH"),
    TrademarkRisk.UNKNOWN: ("grey62", "?"),
}


def _build_table(
    candidates: list[Candidate],
    results: dict[str, CheckResult],
    tm: dict[str, TrademarkResult],
    table_limit: int,
) -> Table:
    order = [(c, results[c.domain]) for c in candidates if c.domain in results]
    order.sort(
        key=lambda pair: (
            _STATUS_ORDER.get(pair[1].status, 9),
            -pair[0].score,
            pair[0].domain,
        )
    )

    table = Table(
        title="[bold]namestack[/bold] - domain availability",
        box=box.SIMPLE_HEAVY,
        header_style="bold white",
        title_justify="left",
    )
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("Domain", style="bold cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Kind", style="dim", no_wrap=True)
    table.add_column("Trademark", justify="center")

    shown = order if table_limit <= 0 else order[:table_limit]
    for i, (c, res) in enumerate(shown, 1):
        status_style, status_label = _STATUS_STYLE.get(
            res.status, ("white", res.status.value)
        )
        tm_res = tm.get(c.name)
        if tm_res is None:
            tm_text, tm_style = ("-", "grey62")
        else:
            tm_style, tm_text = _TM_STYLE.get(
                tm_res.risk, ("white", tm_res.risk.value)
            )
        table.add_row(
            str(i),
            c.domain,
            f"[{status_style}]{status_label}[/]",
            f"{c.score}",
            c.kind,
            f"[{tm_style}]{tm_text}[/]",
        )

    table.caption = f"showing {len(shown)} of {len(order)} checked"
    return table


async def _run_async(
    candidates: list[Candidate],
    checker: AvailabilityChecker,
    *,
    skip_trademark: bool,
    trademark_limit: int,
    offline: bool,
    table_limit: int,
    no_table: bool,
) -> tuple[dict[str, CheckResult], dict[str, TrademarkResult]]:
    results: dict[str, CheckResult] = {}
    tm: dict[str, TrademarkResult] = {}

    table = _build_table(candidates, results, tm, table_limit)
    live = (
        None
        if no_table
        else Live(table, console=console_err, refresh_per_second=12, transient=False)
    )

    last_render = 0.0

    def render(force: bool = False) -> None:
        nonlocal last_render
        if live is None:
            return
        now = time.monotonic()
        if force or now - last_render >= 0.08:
            last_render = now
            live.update(_build_table(candidates, results, tm, table_limit))

    async def on_result(res: CheckResult) -> None:
        results[res.domain] = res
        render()

    ctx = live if live is not None else contextlib.nullcontext()
    with ctx:
        await checker.check_many([c.domain for c in candidates], on_result=on_result)

        if not skip_trademark:
            available = [
                c
                for c in candidates
                if results.get(c.domain) and results[c.domain].status is Status.AVAILABLE
            ]
            targets = available[:trademark_limit] if trademark_limit > 0 else available
            if targets:
                async def on_tm(tres: TrademarkResult) -> None:
                    tm[tres.word] = tres
                    render()

                await check_words(
                    [c.name for c in targets],
                    concurrency=min(5, checker.concurrency),
                    dry_run=offline,
                    on_result=on_tm,
                )
        render(force=True)

    return results, tm


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return "domain,status\n"
    fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _dump(
    candidates: list[Candidate],
    results: dict[str, CheckResult],
    tm: dict[str, TrademarkResult],
    output: str,
    out: Optional[Path],
    available_only: bool,
) -> None:
    fmt = output.lower()
    rows: list[dict] = []
    for c in candidates:
        res = results.get(c.domain)
        if res is None:
            continue
        if available_only and res.status is not Status.AVAILABLE:
            continue
        tm_res = tm.get(c.name)
        rows.append(
            {
                "domain": c.domain,
                "name": c.name,
                "tld": c.tld,
                "status": res.status.value,
                "score": c.score,
                "kind": c.kind,
                "source": res.source,
                "trademark": tm_res.risk.value if tm_res else "",
                "tm_hits": tm_res.total_hits if tm_res else "",
            }
        )
    rows.sort(
        key=lambda r: (
            _STATUS_ORDER.get(Status(r["status"]), 9),
            -r["score"],
            r["domain"],
        )
    )

    if fmt == "csv":
        text = _to_csv(rows)
    elif fmt == "json":
        text = json.dumps(rows, indent=2)
    else:
        return  # table was already the output

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console_err.print(f"[green]Wrote {len(rows)} rows to [bold]{out}[/bold][/green]")
    else:
        console.print(text)


@app.callback(invoke_without_command=True)
def main(
    seeds: str = typer.Option(
        ..., "--seeds", help="Comma-separated seed words (required)."
    ),
    tlds: str = typer.Option("com,io,ai", "--tlds", help="Comma-separated TLDs."),
    concurrency: int = typer.Option(
        20, "--concurrency", help="Max parallel availability lookups."
    ),
    output: str = typer.Option(
        "table", "--output", help="Final dump format: table, csv, or json."
    ),
    out: Optional[Path] = typer.Option(
        None, "--out", help="Write the CSV/JSON dump to this file."
    ),
    limit: int = typer.Option(0, "--limit", help="Cap on candidates to check (0 = all)."),
    min_score: int = typer.Option(
        0, "--min-score", help="Drop candidates below this score (0-100)."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Dry-run: simulate lookups, no network."
    ),
    skip_trademark: bool = typer.Option(
        False, "--skip-trademark", help="Disable USPTO screening."
    ),
    trademark_limit: int = typer.Option(
        20, "--trademark-limit", help="Max wordmarks to screen (0 = all available)."
    ),
    table_limit: int = typer.Option(
        200, "--table-limit", help="Max rows in the live table (0 = all)."
    ),
    no_table: bool = typer.Option(False, "--no-table", help="Suppress the live table."),
    available_only: bool = typer.Option(
        False, "--available", help="Show only available domains."
    ),
) -> None:
    """Generate domain candidates from seed words, check availability in
    parallel, and screen available names for trademark collisions."""
    seed_list = [s.strip() for s in seeds.split(",") if s.strip()]
    tld_list = [t.strip().lstrip(".") for t in tlds.split(",") if t.strip()]
    if not seed_list:
        console_err.print("[red]Provide at least one seed word via --seeds.[/red]")
        raise typer.Exit(1)
    if not tld_list:
        tld_list = ["com", "io", "ai"]

    candidates = generate(
        seed_list, tld_list, min_score=min_score, max_candidates=limit or None
    )
    if not candidates:
        console_err.print(
            "[red]No candidates generated. Lower --min-score or add seeds.[/red]"
        )
        raise typer.Exit(1)

    console_err.print(
        f"Generated [bold]{len(candidates)}[/bold] candidates from "
        f"[bold]{len(seed_list)}[/bold] seed(s) across "
        f"[bold]{len(tld_list)}[/bold] TLD(s)."
    )

    checker = AvailabilityChecker(concurrency=concurrency, dry_run=offline)
    results, tm = asyncio.run(
        _run_async(
            candidates,
            checker,
            skip_trademark=skip_trademark,
            trademark_limit=trademark_limit,
            offline=offline,
            table_limit=table_limit,
            no_table=no_table,
        )
    )

    counts = Counter(r.status for r in results.values())
    summary = ", ".join(
        f"[{_STATUS_STYLE.get(s, ('white', s.value))[0]}]{s.value}={n}[/]"
        for s, n in sorted(counts.items(), key=lambda kv: _STATUS_ORDER.get(kv[0], 9))
    )
    console_err.print(f"Done. {summary}")

    _dump(candidates, results, tm, output, out, available_only)


if __name__ == "__main__":
    app()
