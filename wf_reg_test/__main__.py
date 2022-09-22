import json
import logging
import warnings
from datetime import datetime, timedelta
import random
from typing import cast
from pathlib import Path

import charmonium.time_block as ch_time_block
from rich.prompt import Confirm
from tqdm import tqdm
import yaml

from .engines import engines
from .report import report_html, get_info
from .repos import get_repo_accessor
from .workflows2 import WorkflowApp2, Revision2


logging.basicConfig()
logger = logging.getLogger("wf_reg_test")
logger.setLevel(logging.INFO)
ch_time_block.disable_stderr()


@ch_time_block.decor()
def ensure_revisions(wf_apps: list[WorkflowApp2]) -> None:
    for wf_app in tqdm(wf_apps):
        repo = get_repo_accessor(wf_app.repo_url)
        db_revisions = list(wf_app.revisions)
        observed_revisions = list(repo.get_revisions(wf_app))
        deleted_revisions = [
            drevision
            for drevision in db_revisions
            if not any(orevision.url == drevision.url for orevision in observed_revisions)
        ]
        new_revisions = [
            orevision
            for orevision in observed_revisions
            if not any(orevision.url == drevision.url for drevision in db_revisions)
        ]
        if deleted_revisions:
            warnings.warn(
                f"{len(deleted_revisions)} deleted revisions on repo {repo}",
            )
        wf_app.revisions.extend(new_revisions)


def report(wf_apps: list[WorkflowApp2]) -> None:
    Path("docs/results.html").write_text(report_html(wf_apps))

def ensure_recent_executions(
        wf_apps: list[WorkflowApp2],
        period: timedelta,
        desired_count: int = 1,
        dry_run: bool = False,
) -> None:
    now = datetime.now()
    revisions_to_test: list[tuple[Revision2, int]] = []
    for wf_app in wf_apps:
        for revision in wf_app.revisions:
            existing_count = sum([
                execution.datetime > now - period
                for execution in revision.executions
            ])
            if existing_count < desired_count:
                revisions_to_test.extend([revision] * (desired_count - existing_count))
    random.shuffle(revisions_to_test)
    for revision in revisions_to_test:
        logger.info("Running %s", revision)
        if not dry_run:
            repo = get_repo_accessor(revision.workflow_app.repo_url)
            with repo.checkout(revision.url) as local_copy:
                wf_engine = engines[revision.workflow_app.workflow_engine_name]
                execution = wf_engine.run(local_copy, revision)
                revision.executions.append(execution)
        if not dry_run:
            report(wf_apps)
            data.write_text(yaml.dump(wf_apps))

def check_nodes_are_owned(wf_apps: list[WorkflowApp2]) -> None:
    used_data = {
        revision.tree
        for wf_app in wf_apps
        for revision in wf_app.revisions
    } - {
        execution.output
        for wf_app in wf_apps
        for revision in wf_app.revisions
        for execution in revision.executions
    }
    orphaned_data = set(Path("data").iterdir()) - used_data
    if orphaned_data:
        warnings.warn(f"Orphaned data found: {orphaned_data}")


@ch_time_block.decor()
def main() -> None:
    data = Path("data.yaml")
    wf_apps = cast(list[WorkflowApp2], yaml.load(data.read_text(), Loader=yaml.Loader))
    assert all(isinstance(wf_app, WorkflowApp2) for wf_app in wf_apps)
    logger.info("Before: " + get_info(wf_apps))
    # ensure_revisions(wf_apps)
    # data.write_text(yaml.dump(wf_apps))
    ensure_recent_executions(wf_apps, timedelta(days=100), 2, dry_run=False)
    data.write_text(yaml.dump(wf_apps))
    logger.info("After: " + get_info(wf_apps))
    with ch_time_block.ctx("report_html"):
        report(wf_apps)
    check_nodes_are_owned(wf_apps)


main()


# https://snakemake.github.io/snakemake-workflow-catalog/data.js
# https://github.com/nf-core/nf-co.re/blob/master/update_pipeline_details.php#L85
