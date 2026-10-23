import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import presentbell as pb


class AppearanceTests(unittest.TestCase):
    def test_legacy_and_invalid_style(self):
        state = pb.BellState()
        pb.apply_config(state, {'presentation_duration': 900})
        self.assertEqual(state.style, pb.DEFAULT_STYLE)
        pb.apply_config(state, {'style': {'background': 'bad', 'width': True,
                                         'height': -1, 'font_family': ' '}})
        self.assertEqual(state.style, pb.DEFAULT_STYLE)
        self.assertEqual(state.presentation_duration, 900)

    def test_style_roundtrip_and_partial_override(self):
        state = pb.BellState()
        pb.apply_config(state, {'style': {'background': '#123456', 'width': 200,
                                         'time_font_size': 40}})
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / 'settings.json'
            pb.save_config(state, config)
            restored = pb.BellState()
            pb.apply_config(restored, pb.load_config(config))
        self.assertEqual(restored.style, state.style)
        self.assertEqual(restored.style['accent'], pb.DEFAULT_STYLE['accent'])

    def test_screen_scaling_letterbox_and_negative_monitor(self):
        for monitor, expected in [
            ({'left': 0, 'top': 0, 'width': 1280, 'height': 720}, (1118,6,130,40)),
            ({'left': 0, 'top': 0, 'width': 1920, 'height': 1080}, (1677,9,195,60)),
            ({'left': 0, 'top': 0, 'width': 1280, 'height': 800}, (1118,46,130,40)),
            ({'left': -1920, 'top': -1080, 'width': 1920, 'height': 1080}, (-243,-1071,195,60)),
        ]:
            self.assertEqual(pb.timer_bounds(monitor, pb.DEFAULT_STYLE)[:4], expected)


class PasswordTests(unittest.TestCase):
    def test_default_and_configured_password_roundtrip(self):
        state = pb.BellState()
        self.assertEqual(state.password, 'asdf1234')
        pb.apply_config(state, {'password': 'custom123'})
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / 'settings.json'
            pb.save_config(state, config)
            restored = pb.BellState()
            pb.apply_config(restored, pb.load_config(config))
        self.assertEqual(restored.password, 'custom123')

    def test_invalid_password_keeps_default(self):
        for value in ('', None, 123456, '\u2603'):
            state = pb.BellState()
            pb.apply_config(state, {'password': value})
            self.assertEqual(state.password, pb.DEFAULT_PASSWORD)


class TimingRegressionTests(unittest.TestCase):
    @patch('presentbell.time.monotonic')
    def test_warning_timeout_and_manual_qa(self, clock):
        clock.return_value = 0
        state = pb.BellState()
        state.start_presentation()
        clock.return_value = 480
        self.assertEqual(state.tick()[1], 1)
        self.assertEqual(state.tick()[1], 0)
        clock.return_value = 600
        self.assertEqual(state.tick()[1], 2)
        self.assertEqual(state.tick()[1], 0)
        self.assertEqual(state.phase, 'presentation')
        state.end_presentation_start_qa()
        clock.return_value = 780
        self.assertEqual(state.tick()[1], 1)
        clock.return_value = 900
        self.assertEqual(state.tick()[1], 2)
        self.assertEqual(state.tick()[1], 0)
        self.assertEqual(state.phase, 'done')


if __name__ == '__main__':
    unittest.main()
