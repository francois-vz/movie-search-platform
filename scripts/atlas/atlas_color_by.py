"""Preset the Embedding Atlas view to colour points by a category column.

Why this file exists
--------------------
Embedding Atlas can colour points by a category column, but the CLI has no
option for it, and the gap is not one that configuration can close from outside:

* `embedding-atlas --help` exposes no `--color`. Its data-facing options are
  `--text`, `--image`, `--audio`, `--vector`, `--x`, `--y`, `--neighbors`,
  `--pagerank`, `--query` and `--labels`.
* The frontend *does* accept an `initialState` prop
  (`embedding_atlas/options.py`), but the CLI never passes one: it builds the
  props itself and, when serving, returns them verbatim from
  `GET /data/metadata.json`. `--export-metadata` merges custom metadata only into
  a static export, not into the served document.

So the injection point has to be inside the process. The frontend builds its
default charts by shallow-merging `props.defaultChartsConfig.embedding` over the
default embedding spec, and the JSON schema bundled with the frontend declares
that spec's colour channel as `data.category`.

Merging into the *default* chart is deliberate, and is why this does not set
`initialState.charts` instead: the frontend only generates its default charts
when `initialState.charts` is empty, so supplying charts directly would drop the
data table and the per-column count plots. See
https://github.com/apple/embedding-atlas/issues/88.

Because the merge is shallow, the full set of data channels has to be restated,
not just `category`, or the view loses its x/y and tooltip columns.

Usage
-----
Loaded by `embedding-atlas --with atlas_color_by`, which imports the module
before any data is read. `ATLAS_COLOR_BY` names the column; empty disables the
patch and leaves stock behaviour, in which colouring is a UI click.

This reaches into a private-ish seam of a third-party CLI, so it fails open: any
unexpected shape logs a warning and returns the original props.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from embedding_atlas import cli

logger = logging.getLogger("atlas_color_by")

# Optional channels on the default embedding spec, per its JSON schema. `x` and
# `y` are required and handled separately.
_OPTIONAL_CHANNELS = ("text", "image", "importance", "neighbors")

_original_make_props = cli.make_embedding_atlas_props


def _make_props_with_color_by(**options: Any) -> dict:
    props = _original_make_props(**options)

    column = os.environ.get("ATLAS_COLOR_BY", "").strip()
    if not column:
        return props

    data = props.get("data") or {}
    projection = data.get("projection") or {}
    if "x" not in projection or "y" not in projection:
        logger.warning(
            "ATLAS_COLOR_BY=%s ignored: no projection columns in props, so there "
            "is no embedding chart to colour.",
            column,
        )
        return props

    spec_data: dict[str, Any] = {
        "x": projection["x"],
        "y": projection["y"],
        "category": column,
    }
    for channel in _OPTIONAL_CHANNELS:
        value = data.get(channel)
        if value is not None:
            spec_data[channel] = value

    props["defaultChartsConfig"] = {"embedding": {"data": spec_data}}
    logger.info("Embedding view will colour by %r on load.", column)
    return props


cli.make_embedding_atlas_props = _make_props_with_color_by
