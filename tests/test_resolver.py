from pex.resolver import resolve


def test_empty_resolve():
  empty_resolve = resolve([])
  assert empty_resolve == set()
