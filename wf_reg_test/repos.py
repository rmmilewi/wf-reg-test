from __future__ import annotations

import abc
import dataclasses
import json
import types
from datetime import datetime
from pathlib import Path
from typing import ContextManager, Optional
import urllib.parse

import git
import github
import xxhash

from .workflows import RepoAccessor, Revision, MerkleTreeNode


def get_repo_accessor(url: str) -> RepoAccessor:
    parsed_url = urllib.parse.urlparse(url)
    path = Path(parsed_url.path)
    if parsed_url.netloc  == "github.com" or "git@github:" in parsed_url.netloc:
        if len(path.parts) == 3:
            return GitHubRepo(
                user=path.parts[1],
                repo=path.parts[2].replace(".git", ""),
                only_tags="only_tags" in parsed_url.query,
            )
        else:
            raise NotImplementedError("Only know how to access whole git repositories, not subdirs")
    raise NotImplementedError(f"No known RepoAccessor for {parsed_url!s}")


cache_path = Path(".cache2")


github_client = github.Github(json.loads(Path("secrets.json").read_text())["github"])


@dataclasses.dataclass
class GitHubRepo(RepoAccessor):
    user: str
    repo: str
    only_tags: bool

    @property
    def url(self) -> str:
        return f"https://github.com/{self.user}/{self.repo}"

    def get_revisions(self) -> list[Revision]:
        repo = github_client.get_user(self.user).get_repo(self.repo)
        if self.only_tags:
            revs = ((tag.commit, tag.name) for tag in repo.get_tags())
        else:
            revs = ((commit, commit.sha) for commit in repo.get_commits())
        return [
            Revision(
                display_name=rev,
                url=f"{self.url}/tree/{rev}",
                datetime=commit.commit.committer.date,
            )
            for commit, rev in revs
        ]

    def checkout(self, revision: Revision) -> ContextManager[Path]:
        parsed_url = urllib.parse.urlparse(revision.url)
        path_parts = Path(parsed_url.path).parts
        if path_parts[:4] != ("/", self.user, self.repo, "tree") or len(path_parts) != 5:
            raise ValueError(f"{revision.url} doesn't match {self.url}")
        return GitHubRevision(repo=self, revision=path_parts[4])


@dataclasses.dataclass
class GitHubRevision:
    repo: GitHubRepo
    revision: str

    def __enter__(self) -> Path:
        url_hash = xxhash.xxh32(self.repo.url.encode("utf-8")).hexdigest()
        repo_path = cache_path / url_hash
        if not repo_path.exists():
            repo = git.repo.Repo.clone_from(self.repo.url, repo_path)
        else:
            repo = git.repo.Repo(repo_path)
        with repo:
            repo.head.reset(self.revision, index=True, working_tree=True)
            return repo_path

    def __exit__(
        self,
        _exc_type: Optional[type[BaseException]],
        _exc_value: Optional[BaseException],
        _traceback: Optional[types.TracebackType],
    ) -> None:
        pass