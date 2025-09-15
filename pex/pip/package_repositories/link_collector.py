# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging

from pex.pip.version import PipVersion

logger = logging.getLogger(__name__)


def patch():
    # type: () -> None

    from contextlib import contextmanager

    from pip._internal.index.collector import LinkCollector
    from pip._internal.models.search_scope import SearchScope

    from pex.common import pluralize
    from pex.pep_503 import ProjectName
    from pex.pip.package_repositories import PatchContext
    from pex.typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from typing import Any, Iterator

    patch_context = PatchContext.load()

    @contextmanager
    def scoped_repositories(link_collector, project_name):
        # type: (...) -> Iterator[None]

        project = ProjectName(project_name)
        find_links = patch_context.package_repositories.in_scope_find_links(project)
        if find_links:
            logger.debug(
                "pex: scoped {project_name} to {find_links_repos} {locations}".format(
                    project_name=project_name,
                    find_links_repos=pluralize(find_links, "find links repo"),
                    locations=" and ".join(find_links),
                )
            )
        index_urls = patch_context.package_repositories.in_scope_indexes(project)
        if index_urls:
            logger.debug(
                "pex: scoped {project_name} to {indexes} {locations}".format(
                    project_name=project_name,
                    indexes=pluralize(index_urls, "index"),
                    locations=" and ".join(index_urls),
                )
            )
        if not find_links and not index_urls:
            find_links = list(patch_context.package_repositories.global_find_links)
            index_urls = list(patch_context.package_repositories.global_indexes)

        kwargs = {}
        if patch_context.pip_version >= PipVersion.v22_3:
            kwargs["no_index"] = link_collector.search_scope.no_index

        orig_search_scope = link_collector.search_scope
        link_collector.search_scope = SearchScope.create(
            find_links=find_links, index_urls=index_urls, **kwargs
        )
        try:
            yield
        finally:
            link_collector.search_scope = orig_search_scope

    if patch_context.pip_version is PipVersion.VENDORED:
        orig_collect_links = LinkCollector.collect_links

        def collect_links(
            self,  # type: LinkCollector
            project_name,  # type: str
        ):
            # type: (...) -> Any
            with scoped_repositories(self, project_name):
                return orig_collect_links(self, project_name)

        LinkCollector.collect_links = collect_links
    else:
        orig_collect_sources = LinkCollector.collect_sources

        def collect_sources(
            self,  # type: LinkCollector
            project_name,  # type: str
            *args,  # type: Any
            **kwargs  # type: Any
        ):
            # type: (...) -> Any
            with scoped_repositories(self, project_name):
                return orig_collect_sources(self, project_name, *args, **kwargs)

        LinkCollector.collect_sources = collect_sources
