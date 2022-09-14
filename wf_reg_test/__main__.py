import json
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import sqlalchemy
import sqlalchemy_schemadisplay  # type: ignore

from .engines import engines
from .report import report_html
from .repos import get_repo_accessor
from .workflows import Base, Blob, Execution, MerkleTreeNode, Revision, WorkflowApp


def create_tables(engine: sqlalchemy.engine.Engine) -> None:
    print("Creating tables if it doesn't already exist")
    Base.metadata.create_all(engine)


def clear_tables(engine: sqlalchemy.engine.Engine) -> None:
    print("Clearing tables")
    Base.metadata.drop_all(engine)


def diagram_object_model(path: Path) -> None:
    print(f"Generating diagram {path!s}")
    graph = sqlalchemy_schemadisplay.create_schema_graph(
        metadata=Base.metadata,
        show_datatypes=False,
        show_indexes=False,
        rankdir="LR",
        concentrate=True,
    )
    graph.write_png(path)


def add_default_wf(session: sqlalchemy.orm.Session) -> None:
    wf_apps = [
        WorkflowApp(
            workflow_engine_name="nextflow",
            url="https://nf-co.re/mag",
            display_name="nf-core/mag",
            repo_url="https://github.com/nf-core/mag?only_tags",
        ),
        # WorkflowApp(
        #     workflow_engine_name="nextflow",
        #     url="https://nf-co.re/rnaseq",
        #     display_name="nf-core/rnaseq",
        #     repo_url="https://github.com/nf-core/rnaseq?only_tags"
        # ),
        # WorkflowApp(
        #     workflow_engine_name="nextflow",
        #     url="https://nf-co.re/chipseq",
        #     display_name="nf-core/chipseq",
        #     repo_url="https://github.com/nf-core/chipseq?only_tags"
        # ),
    ]
    with session.begin():
        for wf_app in wf_apps:
            print(f"Adding {wf_app.display_name}")
            session.add(wf_app)


def report(path: Path, session: sqlalchemy.orm.Session) -> None:
    print(f"Generating report {path!s}")
    with session.begin():
        workflow_apps = session.execute(sqlalchemy.select(WorkflowApp)).scalars().all()
        path.write_text(report_html(workflow_apps))


def refresh_revisions(session: sqlalchemy.orm.Session) -> None:
    blobs_in_transaction: dict[int, Blob] = {}
    nodes_in_transaction: dict[int, MerkleTreeNode] = {}
    with session.begin():
        wf_apps = session.execute(sqlalchemy.select(WorkflowApp)).scalars()
        for wf_app in wf_apps:
            repo = get_repo_accessor(wf_app.repo_url)
            db_revisions = set(wf_app.revisions)
            observed_revisions = set(repo.get_revisions())
            deleted_revisions = db_revisions - observed_revisions
            new_revisions = observed_revisions - db_revisions
            if deleted_revisions:
                warnings.warn(
                    f"{len(deleted_revisions)} deleted revisions on repo {repo}",
                )
            for revision in new_revisions:
                print(f"Adding {wf_app.display_name} {revision.display_name}")
                with repo.checkout(revision.url) as local_copy:
                    revision.tree = MerkleTreeNode.from_path(  # type: ignore
                        local_copy,
                        session,
                        nodes_in_transaction,
                        blobs_in_transaction,
                    )
                wf_app.revisions.append(revision)


def run_out_of_date(period: timedelta, session: sqlalchemy.orm.Session) -> None:
    now = datetime.now()
    with session.begin():
        recent_executions = (
            sqlalchemy.select(Execution._revision_id).where(
                Execution.datetime > now - period
            )
        ).subquery()
        revisions_to_test = (
            session.execute(
                sqlalchemy.select(Revision)
                .join(
                    recent_executions,
                    recent_executions.c._revision_id == Revision._id,
                    isouter=True,
                )
                .where(recent_executions.c._revision_id == None)
            )
            .scalars()
            .all()
        )
    with session.begin():
        for revision in revisions_to_test:
            print(
                f"Running {revision.workflow_app.display_name} {revision.display_name}"
            )
            repo = get_repo_accessor(revision.workflow_app.repo_url)
            with repo.checkout(revision.url) as local_copy:
                wf_engine = engines[revision.workflow_app.workflow_engine_name]
                execution = wf_engine.run(local_copy, session)
                revision.executions.append(execution)


def enable_sql_echo() -> None:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def main() -> None:
    logging.basicConfig()
    secrets = json.loads(Path("secrets.json").read_text())
    engine = sqlalchemy.create_engine(secrets["db_url"], future=True)
    with sqlalchemy.orm.Session(engine, future=True) as session:
        restart_db = False
        if restart_db:
            clear_tables(engine)
            create_tables(engine)
            add_default_wf(session)
            diagram_object_model(Path("dbschema.png"))
        else:
            create_tables(engine)

        # refresh_revisions(session)
        run_out_of_date(timedelta(days=100), session)
        report(Path("build/results.html"), session)


main()


# https://snakemake.github.io/snakemake-workflow-catalog/data.js
# https://github.com/nf-core/nf-co.re/blob/master/update_pipeline_details.php#L85
