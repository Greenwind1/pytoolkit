"""MS COCOデータセット関連。

以下の3ファイルを解凍した結果を格納しているディレクトリのパスを受け取って色々処理をする。

- [train2017.zip](http://images.cocodataset.org/zips/train2017.zip)
- [val2017.zip](http://images.cocodataset.org/zips/val2017.zip)
- [annotations_trainval2017.zip](http://images.cocodataset.org/annotations/annotations_trainval2017.zip)

"""
from __future__ import annotations

import pathlib
import typing

import numpy as np

import pytoolkit as tk


def load_coco_od(
    coco_dir, use_crowded: bool = False, verbose: bool = True
) -> typing.Tuple[tk.data.Dataset, tk.data.Dataset]:
    """COCOの物体検出のデータを読み込む。

    References:
        - <https://chainercv.readthedocs.io/en/stable/reference/datasets.html#cocobboxdataset>

    """
    from chainercv.datasets.coco.coco_bbox_dataset import COCOBboxDataset

    ds_train = _load_from_chainercv(
        COCOBboxDataset(
            data_dir=str(coco_dir),
            split="train",
            year="2017",
            use_crowded=use_crowded,
            return_area=True,
            return_crowded=True,
        ),
        desc="load COCO train",
        verbose=verbose,
    )
    ds_val = _load_from_chainercv(
        COCOBboxDataset(
            data_dir=str(coco_dir),
            split="val",
            year="2017",
            use_crowded=use_crowded,
            return_area=True,
            return_crowded=True,
        ),
        desc="load COCO val",
        verbose=verbose,
    )
    return ds_train, ds_val


def _load_from_chainercv(ds, desc, verbose) -> tk.data.Dataset:
    labels = np.array(
        [
            _get_label(ds, i)
            for i in tk.utils.trange(len(ds), desc=desc, disable=not verbose)
        ]
    )
    data = np.array([y.path for y in labels])
    # TODO: metadata={"class_names": CLASS_NAMES}
    return tk.data.Dataset(data=data, labels=labels)


def _get_label(ds, i: int) -> tk.od.ObjectsAnnotation:
    # pylint: disable=protected-access

    # https://github.com/chainer/chainercv/blob/fddc813/chainercv/datasets/coco/coco_instances_base_dataset.py#L66
    path = pathlib.Path(ds.img_root) / ds.id_to_prop[ds.ids[i]]["file_name"]

    height, width = tk.ndimage.get_image_size(path)

    # bbox, label, area, crowded
    bboxes, classes, areas, crowdeds = ds._get_annotations(i)

    # (ymin,xmin,ymax,xmax) -> (xmin,ymin,xmax,ymax)
    bboxes = bboxes[:, [1, 0, 3, 2]].astype(np.float32)
    bboxes[:, [0, 2]] /= width
    bboxes[:, [1, 3]] /= height

    return tk.od.ObjectsAnnotation(
        path=path,
        width=width,
        height=height,
        classes=classes,
        bboxes=bboxes,
        areas=areas,
        crowdeds=crowdeds,
    )
