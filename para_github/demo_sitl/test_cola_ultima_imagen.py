"""Verificación de frescura sin servidores ni simulación."""
import unittest
from cola_ultima_imagen import LatestFramePolicy,replay_policy

class TestLatest(unittest.TestCase):
    def test_pending_is_replaced(self):
        p=LatestFramePolicy();self.assertEqual(p.select(1),(1,[]));self.assertEqual(p.select(4),(4,[2,3]));self.assertEqual(p.select(4),(None,[]))
    def test_deadlines_and_clock_regression(self):
        p=LatestFramePolicy();self.assertTrue(p.may_start(1,2));self.assertFalse(p.may_start(1,2.01));self.assertFalse(p.may_start(1,.99))
        self.assertTrue(p.may_publish(1,2.5));self.assertFalse(p.may_publish(1,2.501))
    def test_burst_does_not_accumulate_fifo(self):
        rows,dropped=replay_policy([1,2,3,4,5,6],[2.6,.2,.2,.2,.2,.2],True)
        self.assertEqual(dropped,[2]);self.assertFalse(rows[0]['published'])
        self.assertTrue(all(r['publish_age_s']<=1.5 for r in rows if r['published']))
        self.assertEqual(len({r['second'] for r in rows}),len(rows))
if __name__=='__main__':unittest.main()
