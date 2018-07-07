import ast


tree = ast.parse(open('test.py', 'r').read())

class FunctionCallVisitor(ast.NodeVisitor):
  def visit_Call(self, node):
    print ast.dump(node)

# FunctionCallVisitor().visit(tree)

# print ast.dump(tree)

# tree.body[0].name

for node in ast.walk(tree):
  print node