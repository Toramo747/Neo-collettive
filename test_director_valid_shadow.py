import ast
import pathlib
import unittest

class DirectorValidShadowRegressionTests(unittest.TestCase):
    def test_revalidation_boolean_does_not_shadow_external_valid_list(self):
        src=pathlib.Path("cloud_mcp.py").read_text(encoding="utf-8")
        self.assertIn("valid = []",src)
        self.assertIn("candidate_valid,reason=validate_observed_candidate(",src)
        self.assertIn("if candidate_valid:",src)
        self.assertNotIn("valid,reason=validate_observed_candidate(",src)

    def test_valid_external_answers_len_remains_list_based(self):
        tree=ast.parse(pathlib.Path("cloud_mcp.py").read_text(encoding="utf-8"))
        assigns=[]
        for node in ast.walk(tree):
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target,ast.Name) and target.id=="valid":
                        assigns.append(node)
        self.assertEqual(len(assigns),1,"director external valid list must not be overwritten")

if __name__=="__main__":
    unittest.main()
