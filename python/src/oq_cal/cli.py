"""``oq-cal`` command-line interface.

Subcommands
-----------
* ``oq-cal validate FILE``:        validate an oq-cal document (exit 0 ok / 1 invalid).
* ``oq-cal convert FILE ...``:     import a source file and/or export an oq-cal doc.
* ``oq-cal diff A B [--json]``:    calibration drift report.
* ``oq-cal summary FILE``:         compact device/calibration overview.
* ``oq-cal formats``:              list registered importers/exporters.

Conversion is routed through :mod:`oq_cal.registry`. This module does not
import converter modules directly. ``load_all()`` runs before any lookup so
importer and exporter modules register themselves.
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime
from pathlib import Path

import click

from . import registry
from .diff import diff as diff_docs
from .io import to_canonical_json
from .models import OqCalDocument
from .validate import validate as validate_doc


# Datum statuses whose placeholder value MUST NOT be treated as a measurement
# (spec §2): excluded from aggregate statistics (best/worst, min/max).
_DEAD_STATUSES = frozenset({"bad", "unmeasured"})


def _is_dead(datum) -> bool:
    return datum is not None and getattr(datum, "status", None) in _DEAD_STATUSES


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_doc(path: str) -> OqCalDocument:
    return OqCalDocument.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _parse_opt_value(raw: str):
    """Coerce a ``--opt`` string value: int -> float -> bool -> str fallback."""
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return raw


def _parse_opts(opts: tuple[str, ...]) -> dict:
    """Parse repeated ``key=value`` strings into a coerced kwargs dict."""
    parsed: dict = {}
    for item in opts:
        if "=" not in item:
            raise click.ClickException(f"--opt must be key=value, got {item!r}")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise click.ClickException(f"--opt has empty key: {item!r}")
        parsed[key] = _parse_opt_value(value)
    return parsed


def _validate_captured_at(raw: str) -> str:
    """Validate an ISO-8601 timestamp, accepting a trailing ``Z`` or an offset.

    Returns the original string unchanged on success; raises a ``ClickException``
    naming the expected form on failure. The value is stored verbatim in the
    document, so we parse only to reject garbage, not to reformat.
    """
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        raise click.ClickException(
            f"--captured-at {raw!r} is not a valid ISO-8601 timestamp; expected "
            "e.g. '2026-10-31T00:00:00Z' or '2026-10-31T00:00:00+00:00'."
        )
    return raw


def _accepted_kwargs(fn, opts: dict) -> dict:
    """Filter ``opts`` to the keyword parameters ``fn`` actually accepts.

    A callable declaring ``**kwargs`` accepts everything; otherwise only its
    named parameters are forwarded.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return {}
    params = sig.parameters.values()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return dict(opts)
    names = {
        p.name
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in opts.items() if k in names}


@click.group()
@click.version_option(package_name="oq-cal", message="%(version)s")
def main() -> None:
    """oq-cal: vendor-neutral QPU calibration interchange."""


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@main.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
def validate(file: str) -> None:
    """Validate FILE against the oq-cal schema and semantic rules."""
    data = _load_json(file)
    issues = validate_doc(data)
    errors = [i for i in issues if i.severity == "error"]
    for issue in issues:
        click.echo(str(issue))
    if errors:
        click.echo(f"INVALID: {len(errors)} error(s)", err=True)
        sys.exit(1)
    click.echo("OK: document is valid")
    sys.exit(0)


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


@main.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--from", "from_fmt", default="oq-cal", help="Source format (importer name, or 'oq-cal').")
@click.option("--to", "to_fmt", default="oq-cal", help="Target format (exporter name, or 'oq-cal').")
@click.option("-o", "--output", type=click.Path(dir_okay=False), default=None, help="Output file (default stdout).")
@click.option("--list-formats", is_flag=True, help="List registered importers/exporters and exit.")
@click.option("--device-id", "device_id", default=None, help="Set device.id on the converted document (overrides any source-derived id and any --opt device_id).")
@click.option("--vendor", default=None, help="Set device.vendor (overrides source and --opt).")
@click.option("--model", default=None, help="Set device.model (overrides source and --opt).")
@click.option(
    "--captured-at",
    "captured_at",
    default=None,
    help=(
        "Set snapshot.captured_at, validated as ISO-8601 (accepts a trailing 'Z' "
        "or an explicit offset, e.g. 2026-10-31T00:00:00Z). Overrides source and "
        "--opt. If omitted and the source carries no capture timestamp, a warning "
        "is printed to stderr and the document is written without one (no mtime "
        "fallback)."
    ),
)
@click.option("--snapshot-id", "snapshot_id", default=None, help="Set snapshot.id on the converted document (overrides source and --opt).")
@click.option(
    "--opt",
    "opts",
    multiple=True,
    metavar="KEY=VALUE",
    help=(
        "Extra option forwarded to the importer and/or exporter (repeatable). "
        "Values are coerced int -> float -> true/false -> str. Each opt is passed "
        "to both the importer and exporter calls, filtered to the parameters each "
        "accepts (via its signature)."
    ),
)
def convert(
    file: str,
    from_fmt: str,
    to_fmt: str,
    output: str | None,
    list_formats: bool,
    device_id: str | None,
    vendor: str | None,
    model: str | None,
    captured_at: str | None,
    snapshot_id: str | None,
    opts: tuple[str, ...],
) -> None:
    """Convert FILE between formats via the converter registry.

    ``--from`` selects an importer (or 'oq-cal' to parse an oq-cal document directly);
    ``--to`` selects an exporter (or 'oq-cal' to emit oq-cal JSON).

    ``--opt key=value`` (repeatable) forwards extra keyword arguments to the
    importer and exporter. Every opt is offered to both calls and filtered by
    each callable's signature, so an importer-only parameter (e.g.
    ``num_qubits`` on the Braket importer) reaches the importer and is ignored
    by the exporter, and vice versa.

    The first-class identity flags (``--device-id``, ``--vendor``, ``--model``,
    ``--captured-at``, ``--snapshot-id``) stamp convert-time device identity and
    capture provenance that the source payload may not carry. They merge into the
    same kwargs stream as ``--opt`` and WIN over any ``--opt`` duplicate.
    ``--captured-at`` is validated as ISO-8601 (trailing ``Z`` or an offset).
    When no ``captured_at`` ends up on the document (neither source nor flag), a
    one-line warning is printed to stderr and conversion proceeds; the file mtime
    is never used as a fallback.
    """
    registry.load_all()

    if list_formats:
        _echo_formats()
        return

    parsed_opts = _parse_opts(opts)

    if captured_at is not None:
        captured_at = _validate_captured_at(captured_at)
    flag_opts = {
        "device_id": device_id,
        "vendor": vendor,
        "model": model,
        "captured_at": captured_at,
        "snapshot_id": snapshot_id,
    }
    for key, value in flag_opts.items():
        if value is not None:
            parsed_opts[key] = value

    if from_fmt == "oq-cal":
        doc = _load_doc(file)
    else:
        try:
            importer = registry.get_importer(from_fmt)
        except KeyError:
            raise click.ClickException(f"unknown importer {from_fmt!r}")
        doc = importer(_load_json(file), **_accepted_kwargs(importer, parsed_opts))
        if doc.snapshot.captured_at is None:
            click.echo(
                "warning: no captured_at in source or flags; document has no "
                "capture timestamp. Pass --captured-at.",
                err=True,
            )

    if to_fmt == "oq-cal":
        # to_canonical_json already includes the trailing newline.
        out_text = to_canonical_json(doc)
    else:
        try:
            exporter = registry.get_exporter(to_fmt)
        except KeyError:
            raise click.ClickException(f"unknown exporter {to_fmt!r}")
        result = exporter(doc, **_accepted_kwargs(exporter, parsed_opts))
        if isinstance(result, (dict, list)):
            out_text = json.dumps(result, indent=2) + "\n"
        else:
            # Non-serialisable target object (e.g. a qiskit Target): describe it.
            out_text = repr(result) + "\n"

    if output:
        # out_text already carries exactly one trailing newline.
        Path(output).write_text(out_text, encoding="utf-8")
        click.echo(f"wrote {output}")
    else:
        # click.echo adds its own newline; strip the one we carry to avoid a
        # doubled blank line on stdout.
        click.echo(out_text.rstrip("\n"))


@main.command()
def formats() -> None:
    """List registered importers and exporters."""
    registry.load_all()
    _echo_formats()


def _echo_formats() -> None:
    fmts = registry.list_formats()
    click.echo("importers: " + (", ".join(fmts["importers"]) or "(none)"))
    click.echo("exporters: " + (", ".join(fmts["exporters"]) or "(none)"))


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@main.command()
@click.argument("a", type=click.Path(exists=True, dir_okay=False))
@click.argument("b", type=click.Path(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Emit the diff as JSON.")
def diff(a: str, b: str, as_json: bool) -> None:
    """Report calibration drift between documents A and B."""
    doc_a = _load_doc(a)
    doc_b = _load_doc(b)
    d = diff_docs(doc_a, doc_b)

    if as_json:
        payload = {
            "summary": d.summary(),
            "entries": [
                {
                    "path": e.path,
                    "a_value": e.a_value,
                    "b_value": e.b_value,
                    "abs_change": e.abs_change,
                    "rel_change": e.rel_change,
                    "significance": e.significance,
                    "a_status": e.a_status,
                    "b_status": e.b_status,
                }
                for e in d.entries
            ],
        }
        click.echo(json.dumps(payload, indent=2))
        return

    # Human-readable table, significance-sorted (major first), then by |rel|.
    order = {"major": 0, "minor": 1, "noise": 2}

    def sort_key(e):
        if e.a_status is not None or e.b_status is not None:
            rel = 0.0
        else:
            rel = abs(e.rel_change) if e.rel_change is not None else float("inf")
        return (order[e.significance], -rel)

    rows = sorted(d.entries, key=sort_key)
    counts = d.counts
    click.echo(
        f"drift: {counts['major']} major, {counts['minor']} minor, "
        f"{counts['noise']} noise ({len(d.entries)} total)"
    )
    click.echo("-" * 72)
    for e in rows:
        if e.a_status is not None or e.b_status is not None:
            av = e.a_status if e.a_status is not None else "-"
            bv = e.b_status if e.b_status is not None else "-"
            click.echo(f"[{e.significance:>5}] {e.path}: {av} -> {bv}")
            continue
        rel = "appeared" if e.a_value is None else (
            "removed" if e.b_value is None else f"{e.rel_change * 100:+.2f}%"
        )
        av = "-" if e.a_value is None else f"{e.a_value:.6g}"
        bv = "-" if e.b_value is None else f"{e.b_value:.6g}"
        click.echo(f"[{e.significance:>5}] {e.path}: {av} -> {bv}  ({rel})")


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


@main.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
def summary(file: str) -> None:
    """Print a compact overview of an oq-cal document."""
    doc = _load_doc(file)
    lines: list[str] = []
    lines.append(f"device:   {doc.device.id} ({doc.device.vendor or '?'} / {doc.device.model or '?'})")
    lines.append(f"qubits:   {doc.device.num_qubits if doc.device.num_qubits is not None else 'unknown'}")
    lines.append(f"snapshot: {doc.snapshot.source} @ {doc.snapshot.captured_at or '?'}")

    sections = []
    if doc.aggregates is not None:
        sections.append("aggregates")
    if doc.qubits:
        sections.append(f"qubits({len(doc.qubits)})")
    if doc.gates:
        sections.append(f"gates({len(doc.gates)})")
    if doc.defcals:
        sections.append(f"defcals({len(doc.defcals)})")
    lines.append("sections: " + (", ".join(sections) or "none"))

    # Per-qubit T1/T2/readout ranges. Dead (bad/unmeasured) datums carry a
    # placeholder value and are excluded from best/worst (spec §2).
    if doc.qubits:
        _range_line(lines, "T1", doc, lambda p: p.t1)
        _range_line(lines, "T2", doc, lambda p: p.t2 or p.t2_echo)
        _range_line(
            lines, "readout_fid", doc,
            lambda p: p.readout.fidelity if p.readout else None,
        )

    # Gate fidelity/error ranges, excluding dead gate entries.
    gate_errs = []
    for g in doc.gates or []:
        if g.error is not None and not _is_dead(g.error):
            gate_errs.append((g.name, g.error.value))
        elif g.fidelity is not None and not _is_dead(g.fidelity):
            gate_errs.append((g.name, 1.0 - g.fidelity.value))
    if gate_errs:
        vals = [v for _, v in gate_errs]
        lines.append(f"gate_err: min {min(vals):.3g}  max {max(vals):.3g}  (n={len(vals)})")

    # Dead-element count line (only when nonzero).
    dead_qubits = 0
    for props in (doc.qubits or {}).values():
        datums = [props.t1, props.t2, props.t2_echo]
        if props.readout is not None:
            datums.append(props.readout.fidelity)
        for bm in props.benchmarks or []:
            datums.append(bm.fidelity)
        if any(_is_dead(d) for d in datums):
            dead_qubits += 1
    dead_gates = sum(
        1 for g in doc.gates or [] if _is_dead(g.error) or _is_dead(g.fidelity)
    )
    if dead_qubits or dead_gates:
        lines.append(
            f"unmeasured: {dead_qubits} qubits, {dead_gates} gate entries"
        )

    click.echo("\n".join(lines))


def _range_line(lines: list[str], label: str, doc: OqCalDocument, getter) -> None:
    pairs = []
    for ref, props in doc.qubits.items():
        datum = getter(props)
        if datum is not None and not _is_dead(datum):
            pairs.append((ref, datum.value))
    if not pairs:
        return
    best = max(pairs, key=lambda x: x[1])
    worst = min(pairs, key=lambda x: x[1])
    lines.append(
        f"{label:>11}: worst {worst[1]:.4g} ({worst[0]})  best {best[1]:.4g} ({best[0]})"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
