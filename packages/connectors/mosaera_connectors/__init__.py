"""Mosaera outbound connectors."""

from mosaera_connectors.backlog import BacklogProvider, DraftItem
from mosaera_connectors.github import (
    GitHubPRResult,
    GitHubPushResult,
    PullRequestPlan,
    assemble_pull_request,
    open_pull_request,
    push_branch,
)
from mosaera_connectors.gitlab import (
    MergeRequestPlan,
    MergeRequestResult,
    assemble_merge_request,
    check_repo_access,
    delete_remote_branch,
    inject_repo_token,
    is_gitlab_source,
    open_merge_request,
    project_from_source,
)
from mosaera_connectors.provider import DeliveryProvider, detect_delivery_provider

__all__ = [
    "BacklogProvider",
    "DeliveryProvider",
    "DraftItem",
    "GitHubPRResult",
    "GitHubPushResult",
    "MergeRequestPlan",
    "MergeRequestResult",
    "PullRequestPlan",
    "assemble_merge_request",
    "assemble_pull_request",
    "check_repo_access",
    "delete_remote_branch",
    "detect_delivery_provider",
    "inject_repo_token",
    "is_gitlab_source",
    "open_merge_request",
    "open_pull_request",
    "project_from_source",
    "push_branch",
]
