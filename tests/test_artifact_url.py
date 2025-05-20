# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.artifact_url import VCS, ArchiveScheme, VCSScheme, parse_scheme


def test_parse_scheme():
    # type: () -> None

    assert "not a scheme" == parse_scheme("not a scheme")
    assert "gopher" == parse_scheme("gopher")

    assert ArchiveScheme.FTP == parse_scheme("ftp")
    assert ArchiveScheme.HTTP == parse_scheme("http")
    assert ArchiveScheme.HTTPS == parse_scheme("https")

    assert VCSScheme(VCS.Bazaar, "nfs") == parse_scheme("bzr+nfs")
    assert VCSScheme(VCS.Git, "file") == parse_scheme("git+file")
    assert VCSScheme(VCS.Mercurial, "http") == parse_scheme("hg+http")
    assert VCSScheme(VCS.Subversion, "https") == parse_scheme("svn+https")

    assert "cvs+https" == parse_scheme("cvs+https")
