"""Additional independently authored cut-provenance and alias regressions."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(os.environ.get('AUDIT_SKILL',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT/'scripts'))
import subtitle_core as core
import content_filter_pipeline as cuts

class AuditExtensionTests(unittest.TestCase):
    def test_cut_evidence_requires_a_genuinely_prepared_job(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);job=root/'fake-job';job.mkdir()
            core.write_json(job/'job.json',{})
            core.write_json(job/'context.json',{'title':'Not a prepared subtitle job'})
            with self.assertRaises(ValueError):
                cuts.persist_cut_evidence(job,{'status':'unbound evidence'},root/'archive')
            self.assertFalse(list(root.rglob('cut-*.json')))
    def test_compatibility_link_resolves_to_canonical_skill(self):
        # The shared workspace keeps the legacy entry beside the canonical
        # skill; standalone audit ZIPs keep it under COMPATIBILITY/.
        candidates=(ROOT.parent/'anime-subtitle-pipeline/SKILL.md',
                    ROOT.parent/'COMPATIBILITY/anime-subtitle-pipeline/SKILL.md')
        path=next((p for p in candidates if p.is_file()),candidates[-1])
        import re
        target=re.search(r'\]\(([^)]+SKILL.md)\)',path.read_text()).group(1)
        self.assertEqual((path.parent/target).resolve(),(ROOT/'SKILL.md').resolve())
        self.assertTrue((path.parent/target).is_file())

if __name__=='__main__':unittest.main()
