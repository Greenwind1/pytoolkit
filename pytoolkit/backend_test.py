import pytest
import tensorflow as tf

import pytoolkit as tk


def test_logit():
    x = tf.constant([0.0, 0.5, 1.0])
    y = [-16.118095, 0, +16.118095]
    logits = tk.backend.logit(x).numpy()
    assert logits == pytest.approx(y, abs=1e-6)
