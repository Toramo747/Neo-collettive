import unittest

from tools.dependency_audit import _canonical_license, _primary_license_evidence


class _Meta:
    def __init__(self, values=None, classifiers=None):
        self.values=values or {}
        self.classifiers=classifiers or []
    def get(self,key,default=None):
        return self.values.get(key,default)
    def get_all(self,key):
        if key=="Classifier":
            return list(self.classifiers)
        return []


class DependencyAuditLicenseTests(unittest.TestCase):
    def test_bsd_classifier_is_primary_over_bundled_lgpl_notice(self):
        meta=_Meta(
            values={
                "License":"BSD License\nBundled component: libquadmath\nLicense: LGPL-2.1-or-later",
            },
            classifiers=["License :: OSI Approved :: BSD License"],
        )
        raw,classifier=_primary_license_evidence(meta)
        self.assertEqual(raw,"")
        normalized,status=_canonical_license(raw,classifier)
        self.assertEqual(status,"allowed")
        self.assertEqual(normalized,"BSD")

    def test_license_expression_has_priority(self):
        meta=_Meta(
            values={"License-Expression":"Apache-2.0","License":"legacy text"},
            classifiers=["License :: OSI Approved :: MIT License"],
        )
        raw,classifier=_primary_license_evidence(meta)
        self.assertEqual(raw,"Apache-2.0")
        self.assertEqual(classifier,"")
        self.assertEqual(_canonical_license(raw,classifier)[1],"allowed")

    def test_primary_gpl_classifier_remains_blocked(self):
        meta=_Meta(
            values={"License":"irrelevant bundled text"},
            classifiers=["License :: OSI Approved :: GNU General Public License v3 (GPLv3)"],
        )
        raw,classifier=_primary_license_evidence(meta)
        self.assertEqual(raw,"")
        self.assertEqual(_canonical_license(raw,classifier)[1],"blocked")

    def test_unknown_primary_license_stays_unknown(self):
        self.assertEqual(_canonical_license("Custom-Proprietary","")[1],"unknown")


if __name__=="__main__":
    unittest.main()
