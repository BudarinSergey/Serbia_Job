import unittest
from unittest.mock import patch, call
import sqlite3
import main
from sources.infostud import InfostudError


class ScheduleTests(unittest.TestCase):
    @patch('main.time.sleep', side_effect=[None, KeyboardInterrupt])
    @patch('main.check_once', side_effect=[1, 0])
    def test_immediate_check_and_hourly_retry(self, check, sleep):
        events = []
        check.side_effect = lambda: events.append('check') or 0
        def wait(seconds):
            events.append(seconds)
            if len(events) == 4:
                raise KeyboardInterrupt
        sleep.side_effect = wait
        with self.assertRaises(KeyboardInterrupt):
            main.run_hourly()
        self.assertEqual(events, ['check', 3600, 'check', 3600])

    @patch('main.time.sleep', side_effect=[None, KeyboardInterrupt])
    @patch('main.run_cycle', return_value=1)
    def test_network_error_does_not_stop_schedule(self, fetch, sleep):
        with self.assertRaises(KeyboardInterrupt):
            main.run_hourly()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(sleep.call_args_list, [call(3600), call(3600)])

    @patch('main.run_cycle', return_value=1)
    def test_storage_failure_is_reported(self, cycle):
        self.assertEqual(main.check_once(), 1)

    @patch('main.run_hourly')
    @patch('main.check_once', return_value=1)
    def test_once_preserves_exit_status(self, check, hourly):
        self.assertEqual(main.main(['--once']), 1)
        check.assert_called_once()
        hourly.assert_not_called()

    @patch('threading.Thread')
    @patch('main.run_hourly', side_effect=KeyboardInterrupt)
    def test_stop_is_clean(self, hourly, thread):
        self.assertEqual(main.main([]), 0)
        thread.return_value.start.assert_called_once()
