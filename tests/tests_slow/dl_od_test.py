import pathlib

import numpy as np

import pytoolkit as tk


def test_od(data_dir, tmpdir):
    result_dir = pathlib.Path(str(tmpdir))

    class_name_to_id = {'～': 0, '〇': 1}
    X, y = tk.data.voc.load_annotations(data_dir / 'od', data_dir / 'od' / 'Annotations', class_name_to_id=class_name_to_id)
    X = np.array([data_dir / 'od' / 'JPEGImages' / (p.stem + '.png') for p in X])  # TODO: VoTT対応

    with tk.dl.session():
        od = tk.dl.od.ObjectDetector((128, 128), [8], 2)
        od.fit(X, y, X, y,
               batch_size=1, epochs=1,
               initial_weights=None,
               pb_size_pattern_count=8,
               flip_h=False, flip_v=False, rotate90=False,
               plot_path=result_dir / 'model.svg',
               tsv_log_path=result_dir / 'history.tsv')
        od.save(result_dir / 'model.json')
        od.save_weights(result_dir / 'model.h5')
        del od

    with tk.dl.session():
        od = tk.dl.od.ObjectDetector.load(result_dir / 'model.json')
        od.load_weights(result_dir / 'model.h5', batch_size=1, strict_nms=True, use_multi_gpu=False)
        pred = od.predict(X, conf_threshold=0.25)
        assert len(pred) == len(y)