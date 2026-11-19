"""FA1's control plane, as a backend: Robinauts' parts and FA1's own applications, composed on
oneberth (docs/specs/apps.md). This file is the backend's list of applications. main.tsx is the
rail's.

Robinauts' parts read the environment as `robinauts start` does: ROBINAUTS_CONFIG,
ROBINAUTS_DATA_DIR and ROBINAUTS_FLOWS_DIR. The review app reads three more: REVIEWS_WORK, the
designer's working copy of the setup folder; REVIEWS_PUBLISHED, the bundle of the setup
folder's HEAD, which the app writes; and FA1_SETUP_KEY, the key of the designer's tools. The
launch secret is the first line of standard input. The front listener binds every
address of the container, and a browser reaches it on the host's loopback. The worker listener
is on the container's loopback, where the code worker reaches it (docs/specs/containers.md,
"Network").
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from oneberth.web import Listen, compose_app, run
from robinauts.cli.backend import robinauts_parts
from robinauts.controller.contract.domain import ConfigError

from reviews.backend import reviews

INTERFACE = Path(__file__).resolve().parent / "dist"
"""The built interface: main.tsx and what it imports, as the image's build leaves it."""

NO_DATA_DIR = (
    "ROBINAUTS_DATA_DIR names no folder: the control plane keeps its records there, and so do"
    " FA1's applications"
)
NO_REVIEWS = (
    "{} names no path: the review app reads the designer's working copy at REVIEWS_WORK, and the"
    " setup folder's HEAD in the bundle REVIEWS_PUBLISHED"
)
TOOLS_PORT = 8422
"""The port of the designer's two tools, on the control plane's loopback address
(docs/specs/review-app.md, "The designer's tools")."""


def main() -> int:
    parser = argparse.ArgumentParser(description="FA1's control plane")
    parser.add_argument("--port", type=int, required=True, help="the front listener's")
    parser.add_argument("--worker-port", type=int, required=True, help="the worker listener's")
    arguments = parser.parse_args()
    front = Listen("0.0.0.0", arguments.port)
    worker = Listen("127.0.0.1", arguments.worker_port)
    data = os.environ.get("ROBINAUTS_DATA_DIR")
    if not data:
        print(NO_DATA_DIR, file=sys.stderr)
        return 1
    for variable in ("REVIEWS_WORK", "REVIEWS_PUBLISHED"):
        if not os.environ.get(variable):
            print(NO_REVIEWS.format(variable), file=sys.stderr)
            return 1
    config = os.environ.get("ROBINAUTS_CONFIG")
    flows = os.environ.get("ROBINAUTS_FLOWS_DIR")
    review = reviews(
        Path(data),
        work=Path(os.environ["REVIEWS_WORK"]),
        published=Path(os.environ["REVIEWS_PUBLISHED"]),
        config=Path(config) if config else None,
        flows=Path(flows) if flows else None,
        tools_key=os.environ.get("FA1_SETUP_KEY", ""),
        tools_port=TOOLS_PORT,
    )
    try:
        robinauts = robinauts_parts(
            os.environ, front=front, worker=worker, local=True, public_host="127.0.0.1"
        )
    except ConfigError as refused:
        print(refused, file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO)
    composition = compose_app(
        [*robinauts.components, review],
        config=robinauts.oneberth,
        store=robinauts.store,
        interface=INTERFACE,
        local=robinauts.local,
    )
    robinauts.composed_into(composition)
    run(composition, front, worker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
