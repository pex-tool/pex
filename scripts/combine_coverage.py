import os
import pprint
import sys

from coverage.data import CoverageData
from pex.pex_builder import PEXBuilder


def _iter_filter(root_dir, data_dict):
  root_fragment = os.path.join(root_dir, 'pex/')
  pex_fragment = '/%s/_pex/' % PEXBuilder.BOOTSTRAP_DIR

  for filename, records in data_dict.items():
    # already acceptable coverage
    if filename.startswith(root_fragment):
      yield (filename, dict((record, None) for record in records))
      continue

    # possible it's coverage from within a pex environment
    try:
      bi = filename.index(pex_fragment)
    except ValueError:
      continue

    # rewrite to make up for fact that each pex environment is ephemeral.
    yield (
        os.path.join(root_dir, 'pex', filename[bi + len(pex_fragment):]),
        dict((record, None) for record in records)
    )


def combine_pex_coverage(root_dir, coverage_file_iter, unlink=True):
  combined = CoverageData(basename='.coverage')

  for filename in coverage_file_iter:
    cov = CoverageData(basename=filename)
    cov.read()
    combined.add_line_data(dict(_iter_filter(root_dir, cov.line_data())))
    combined.add_arc_data(dict(_iter_filter(root_dir, cov.arc_data())))
    os.unlink(filename)

  # filter out non-pex files
  prefix = os.path.join(root_dir, 'pex/')
  non_pex = [filename for filename in combined.lines if not filename.startswith(prefix)]
  for filename in non_pex:
    combined.lines.pop(filename)

  non_pex = [filename for filename in combined.arcs if not filename.startswith(prefix)]
  for filename in non_pex:
    combined.arcs.pop(filename)

  combined.write()
  return combined.filename


def main(args):
  script = os.path.realpath(args[0])
  root = os.path.realpath(os.path.join(os.path.dirname(script), '..'))

  coverage_iterator = [
      os.path.join(root, filename) for filename in os.listdir(root)
      if filename.startswith('.coverage')]

  combine_pex_coverage(root, coverage_iterator, unlink=False)


if __name__ == '__main__':
  main(sys.argv)
