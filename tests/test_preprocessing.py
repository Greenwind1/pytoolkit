import pytest
import pandas as pd
import numpy as np
import pytoolkit as tk


def test_normalizer():
    df = pd.DataFrame()
    df["a"] = [1, 2, 3, 4]
    df["b"] = [0, 1, 0, 1]
    df["c"] = [0.0, 1.0, 0.0, np.nan]
    df["d"] = [1, 1, None, 1]

    r1 = tk.preprocessing.Normalizer().fit_transform(df)
    r2 = tk.preprocessing.Normalizer().fit_transform(df.values)

    assert r1["a"].values == pytest.approx(r2[:, 0])
    assert r1["b"].values == pytest.approx(r2[:, 1])
    assert r1["c"].values == pytest.approx(r2[:, 2], nan_ok=True)
    assert r1["d"].values == pytest.approx(r2[:, 3], nan_ok=True)

    assert r1["a"].values == pytest.approx(
        [-1.3416407, -0.4472136, 0.4472136, 1.3416407]
    )
    assert r1["b"].values == pytest.approx([-1, 1, -1, 1])
    assert r1["c"].values == pytest.approx([0, 2.1213205, 0, np.nan], nan_ok=True)
    assert r1["d"].values == pytest.approx([0, 0, np.nan, 0], nan_ok=True)


def test_target_encoder():
    df = pd.DataFrame()
    df["a"] = ["a", "b", "a", "b"]
    df["b"] = [0, 1, 0, 1]
    df["c"] = [0.0, 1.0, 0.0, np.nan]
    df["d"] = [0, 1, 0, 1]
    df["b"] = df["b"].astype("category")
    y = np.array([1, 3, 5, 7])

    encoder = tk.preprocessing.TargetEncoder(cols=["a", "b", "c"], min_samples_leaf=1)
    encoder.fit(df, y)
    df2 = encoder.transform(df)

    assert df2["a"].values == pytest.approx([1.0, 2.0, 1.0, 2.0])
    assert df2["b"].values == pytest.approx([1.0, 2.0, 1.0, 2.0])
    assert df2["c"].values == pytest.approx([1.0, 2.0, 1.0, np.nan], nan_ok=True)
    assert df2["d"].values == pytest.approx([0, 1, 0, 1])