from __future__ import annotations

import datetime
import enum
import pathlib
import typing as t
from typing import Annotated, Any, Literal, TypeVar

import yaml
from pydantic import AnyUrl as PydanticAnyUrl
from pydantic import (
    BaseModel,
    DirectoryPath,
    Field,
    FilePath,
    PrivateAttr,
    StringConstraints,
    TypeAdapter,
    field_validator,
)
from pydantic import HttpUrl as PydanticHttpUrl
from pydantic.functional_validators import AfterValidator

from .command import Command, SafeLoader


class ModelWithCommand(BaseModel):
    """Base class for a model that has a Helm command object."""

    # The command object that is used to invoke Helm
    _command: Command = PrivateAttr()

    def __init__(self, _command: Command, **kwargs):
        super().__init__(**kwargs)
        self._command = _command


#: Type for a non-empty string
NonEmptyString = Annotated[
    str,
    StringConstraints(
        min_length=1,
    ),
]

#: Type for a name (chart or release)
Name = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-z0-9-]+$",
    ),
]


#: Type for a SemVer version
SemVerVersion = Annotated[
    str,
    StringConstraints(
        pattern=r"^v?\d+\.\d+\.\d+(-[a-zA-Z0-9\.\-]+)?(\+[a-zA-Z0-9\.\-]+)?$",
    ),
]


#: Type variables for forward references to the chart and release types
ChartType = TypeVar("ChartType", bound="Chart")
ReleaseType = TypeVar("ReleaseType", bound="Release")


#: Type annotation for validating a string using a Pydantic type
def validate_str_as(validate_type: type):  # noqa
    adapter = TypeAdapter(validate_type)
    return lambda v: str(adapter.validate_python(v))


#: Annotated string types for URLs
AnyUrl = Annotated[str, AfterValidator(validate_str_as(PydanticAnyUrl))]
HttpUrl = Annotated[str, AfterValidator(validate_str_as(PydanticHttpUrl))]
OCIPath = Annotated[str, Field(pattern=r"oci:\/\/*")]


class ChartDependency(BaseModel):
    """Model for a chart dependency."""

    name: Name = Field(
        ...,
        description="The name of the chart.",
    )
    version: NonEmptyString = Field(
        ...,
        description="The version of the chart. Can be a SemVer range.",
    )
    repository: str = Field(
        "",
        description="The repository URL or alias.",
    )
    condition: NonEmptyString | None = Field(
        None,
        description="A yaml path that resolves to a boolean, used for enabling/disabling the chart.",
    )
    tags: list[NonEmptyString] = Field(
        default_factory=list,
        description="Tags can be used to group charts for enabling/disabling together.",
    )
    import_values: list[dict[str, str] | str] = Field(
        default_factory=list,
        alias="import-values",
        description=(
            "Mapping of source values to parent key to be imported. "
            "Each item can be a string or pair of child/parent sublist items."
        ),
    )
    alias: NonEmptyString | None = Field(
        None,
        description="Alias to be used for the chart.",
    )


class ChartMaintainer(BaseModel):
    """Model for the maintainer of a chart."""

    name: NonEmptyString = Field(
        ...,
        description="The maintainer's name.",
    )
    email: NonEmptyString | None = Field(
        None,
        description="The maintainer's email.",
    )
    url: AnyUrl | None = Field(
        None,
        description="A URL for the maintainer.",
    )


class ChartMetadata(BaseModel):
    """Model for chart metadata, from Chart.yaml."""

    api_version: Literal["v1", "v2"] = Field(
        ...,
        alias="apiVersion",
        description="The chart API version.",
    )
    name: Name = Field(
        ...,
        description="The name of the chart.",
    )
    version: SemVerVersion = Field(
        ...,
        description="The version of the chart.",
    )
    kube_version: NonEmptyString | None = Field(
        None,
        alias="kubeVersion",
        description="A SemVer range of compatible Kubernetes versions for the chart.",
    )
    description: NonEmptyString | None = Field(
        None,
        description="A single-sentence description of the chart.",
    )
    type: Literal["application", "library"] = Field(
        "application",
        description="The type of the chart.",
    )
    keywords: list[NonEmptyString] = Field(
        default_factory=list,
        description="List of keywords for the chart.",
    )
    home: HttpUrl | None = Field(
        None,
        description="The URL of th home page for the chart.",
    )
    sources: list[AnyUrl] = Field(
        default_factory=list,
        description="List of URLs to source code for this chart.",
    )
    dependencies: list[ChartDependency] = Field(
        default_factory=list,
        description="List of the chart dependencies.",
    )
    maintainers: list[ChartMaintainer] = Field(
        default_factory=list,
        description="List of maintainers for the chart.",
    )
    icon: HttpUrl | None = Field(
        None,
        description="URL to an SVG or PNG image to be used as an icon.",
    )
    app_version: NonEmptyString | None = Field(
        None,
        alias="appVersion",
        description=("The version of the app that this chart deploys. SemVer is not required."),
    )
    deprecated: bool = Field(
        False,
        description="Whether this chart is deprecated.",
    )
    annotations: dict[str, str] = Field(
        default_factory=dict,
        description="Annotations for the chart.",
    )


class Chart(ModelWithCommand):
    """Model for a reference to a chart."""

    ref: DirectoryPath | FilePath | HttpUrl | Name | OCIPath = Field(
        ...,
        description=(
            "The chart reference. "
            "Can be a chart directory or a packaged chart archive on the local "
            "filesystem, the URL of a packaged chart or the name of a chart, or a oci registry. "
            "When a name is given, repo must also be given and version may optionally "
            "be given."
        ),
    )
    repo: HttpUrl | None = Field(default=None, description="The repository URL.")
    metadata: ChartMetadata = Field(..., description="The metadata for the chart.")

    # Private attributes used to cache attributes
    _readme: str | None = PrivateAttr(None)
    _crds: list[dict[str, Any]] | None = PrivateAttr(None)
    _values: dict[str, Any] | None = PrivateAttr(None)

    @field_validator("ref")
    def ref_is_abspath(cls, v):  # noqa
        """If the ref is a path on the filesystem, make sure it is absolute."""
        if isinstance(v, pathlib.Path):
            return v.resolve()
        else:
            return v

    async def _run_command(self, command_method):  # noqa
        """Runs the specified command for this chart."""
        method = getattr(self._command, command_method)
        # We only need the kwargs if the ref is not a direct reference
        if isinstance(self.ref, pathlib.Path | HttpUrl):  # type: ignore
            return await method(self.ref)
        else:
            return await method(self.ref, repo=self.repo, version=self.metadata.version)


class Release(ModelWithCommand):
    """Model for a Helm release."""

    name: Name = Field(
        ...,
        description="The name of the release.",
    )
    namespace: Name = Field(
        ...,
        description="The namespace of the release.",
    )

    async def current_revision(self) -> ReleaseRevision:
        """Returns the current revision for the release."""
        return ReleaseRevision._from_status(
            await self._command.status(
                self.name,
                namespace=self.namespace,
            ),
            self._command,
        )

    async def revision(self, revision: int) -> ReleaseRevision:
        """Returns the specified revision for the release."""
        return ReleaseRevision._from_status(
            await self._command.status(
                self.name,
                namespace=self.namespace,
                revision=revision,
            ),
            self._command,
        )

    async def rollback(
        self,
        revision: int | None = None,
        *,
        cleanup_on_fail: bool = False,
        dry_run: bool = False,
        force: bool = False,
        no_hooks: bool = False,
        recreate_pods: bool = False,
        timeout: int | str | None = None,
        wait: bool = False,
    ) -> ReleaseRevision:
        """Rollback this release to the specified version and return the resulting revision.

        If no revision is specified, it will rollback to the previous release.
        """
        await self._command.rollback(
            self.name,
            revision,
            cleanup_on_fail=cleanup_on_fail,
            dry_run=dry_run,
            force=force,
            namespace=self.namespace,
            no_hooks=no_hooks,
            recreate_pods=recreate_pods,
            timeout=timeout,
            wait=wait,
        )
        return await self.current_revision()

    async def uninstall(
        self,
        *,
        dry_run: bool = False,
        keep_history: bool = False,
        no_hooks: bool = False,
        timeout: int | str | None = None,
        wait: bool = False,
    ):
        """Uninstalls this release."""
        await self._command.uninstall(
            self.name,
            dry_run=dry_run,
            keep_history=keep_history,
            namespace=self.namespace,
            no_hooks=no_hooks,
            timeout=timeout,
            wait=wait,
        )


class ReleaseRevisionStatus(str, enum.Enum):
    """Enumeration of possible release statuses."""

    #: Indicates that the revision is in an uncertain state
    UNKNOWN = "unknown"
    #: Indicates that the revision has been pushed to Kubernetes
    DEPLOYED = "deployed"
    #: Indicates that the revision has been uninstalled from Kubernetes
    UNINSTALLED = "uninstalled"
    #: Indicates that the revision is outdated and a newer one exists
    SUPERSEDED = "superseded"
    #: Indicates that the revision was not successfully deployed
    FAILED = "failed"
    #: Indicates that an uninstall operation is underway for this revision
    UNINSTALLING = "uninstalling"
    #: Indicates that an install operation is underway for this revision
    PENDING_INSTALL = "pending-install"
    #: Indicates that an upgrade operation is underway for this revision
    PENDING_UPGRADE = "pending-upgrade"
    #: Indicates that a rollback operation is underway for this revision
    PENDING_ROLLBACK = "pending-rollback"


class HookEvent(str, enum.Enum):
    """Enumeration of possible hook events."""

    PRE_INSTALL = "pre-install"
    POST_INSTALL = "post-install"
    PRE_DELETE = "pre-delete"
    POST_DELETE = "post-delete"
    PRE_UPGRADE = "pre-upgrade"
    POST_UPGRADE = "post-upgrade"
    PRE_ROLLBACK = "pre-rollback"
    POST_ROLLBACK = "post-rollback"
    TEST = "test"


class HookDeletePolicy(str, enum.Enum):
    """Enumeration of possible delete policies for a hook."""

    HOOK_SUCCEEDED = "hook-succeeded"
    HOOK_FAILED = "hook-failed"
    HOOK_BEFORE_HOOK_CREATION = "before-hook-creation"


class HookPhase(str, enum.Enum):
    """Enumeration of possible phases for a hook."""

    #: Indicates that a hook is in an unknown state
    UNKNOWN = "Unknown"
    #: Indicates that a hook is currently executing
    RUNNING = "Running"
    #: Indicates that hook execution succeeded
    SUCCEEDED = "Succeeded"
    #: Indicates that hook execution failed
    FAILED = "Failed"


class Hook(BaseModel):
    """Model for a hook."""

    name: NonEmptyString = Field(
        ...,
        description="The name of the hook.",
    )
    phase: HookPhase = Field(
        HookPhase.UNKNOWN,
        description="The phase of the hook.",
    )
    kind: NonEmptyString = Field(
        ...,
        description="The kind of the hook.",
    )
    path: NonEmptyString = Field(
        ...,
        description="The chart-relative path to the template that produced the hook.",
    )
    resource: dict[str, t.Any] = Field(
        ...,
        description="The resource for the hook.",
    )
    events: list[HookEvent] = Field(
        default_factory=list,
        description="The events that the hook fires on.",
    )
    delete_policies: list[HookDeletePolicy] = Field(
        default_factory=list,
        description="The delete policies for the hook.",
    )


class ReleaseRevision(ModelWithCommand):
    """Model for a revision of a release."""

    release: Release = Field(
        ...,
        description="The parent release of this revision.",
    )
    revision: int = Field(
        ...,
        description="The revision number of this revision.",
    )
    status: ReleaseRevisionStatus = Field(
        ...,
        description="The status of the revision.",
    )
    updated: datetime.datetime = Field(
        ...,
        description="The time at which this revision was updated.",
    )
    description: NonEmptyString | None = Field(
        None,
        description="'Log entry' for this revision.",
    )
    notes: NonEmptyString | None = Field(
        None,
        description="The rendered notes for this revision, if available.",
    )

    # Optional fields if they are known at creation time
    chart_metadata_: ChartMetadata | None = Field(None, alias="chart_metadata")
    hooks_: list[dict[str, t.Any]] | None = Field(None, alias="hooks")
    resources_: list[dict[str, t.Any]] | None = Field(None, alias="resources")
    values_: dict[str, t.Any] | None = Field(None, alias="values")

    def _set_from_status(self, status: dict[str, Any]):
        # Statuses from install/upgrade have chart metadata embedded
        if "chart" in status:
            self.chart_metadata_ = ChartMetadata(**status["chart"]["metadata"])
        self.hooks_ = [  # type: ignore
            Hook(
                name=hook["name"],
                phase=hook["last_run"].get("phase") or "Unknown",  # type: ignore
                kind=hook["kind"],
                path=hook["path"],
                resource=yaml.load(hook["manifest"], Loader=SafeLoader),
                events=hook["events"],
                delete_policies=hook.get("delete_policies", []),
            )
            for hook in status.get("hooks", [])
        ]
        self.resources_ = list(yaml.load_all(status["manifest"], Loader=SafeLoader))

    @classmethod
    def _from_status(cls, status: dict[str, Any], command: Command) -> ReleaseRevision:
        """Internal constructor to create a release revision from a status result."""
        revision = ReleaseRevision(
            command,  # type: ignore
            release=Release(
                command,  # type: ignore
                name=status["name"],
                namespace=status["namespace"],
            ),
            revision=status["version"],
            status=status["info"]["status"],
            updated=status["info"]["last_deployed"],
            description=status["info"].get("description"),
            notes=status["info"].get("notes"),
        )
        revision._set_from_status(status)
        return revision
