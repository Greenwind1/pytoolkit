"""機械学習(主にsklearn)関連。"""
import json
import multiprocessing as mp
import pathlib

import numpy as np
import sklearn.base
import sklearn.model_selection
import sklearn.utils


class WeakModel(object):
    """CVしたりout-of-folds predictionを作ったりするクラス。"""

    def __init__(self, model_dir, base_estimator, cv=5, fit_params=None):
        self.model_dir = pathlib.Path(model_dir)
        self.base_estimator = base_estimator
        self.cv = cv
        self.fit_params = fit_params
        self.estimators_ = None
        self.data_ = {}

    def fit(self, X, y, groups=None, pool=None):
        """学習"""
        if not pool:
            pool = mp.Pool()
        func, args = self.make_fit_tasks(X, y, groups)
        pool.map(func, args)

    def make_fit_tasks(self, X, y, groups=None):
        """学習の処理を作って返す。(func, args)形式。"""
        self._init_data()
        args = []
        for fold in range(self.cv):
            estimator = sklearn.base.clone(self.base_estimator)
            args.append((estimator, fold, X, y, groups))
        return self._fit, args

    def split(self, fold, X, y, groups=None):
        """データの分割"""
        rs = np.random.RandomState(self.data_['split_seed'])
        classifier = sklearn.base.is_classifier(self.base_estimator)
        # cv = sklearn.model_selection.check_cv(self.cv, y, classifier=classifier)
        if classifier:
            cv = sklearn.model_selection.StratifiedKFold(n_splits=self.cv, shuffle=True, random_state=rs)
        else:
            cv = sklearn.model_selection.KFold(n_splits=self.cv, shuffle=True, random_state=rs)
        return list(cv.split(X, y, groups))[fold]

    def _fit(self, estimator, fold, X, y, groups=None):
        """学習。"""
        X, y, groups = sklearn.utils.indexable(X, y, groups)  # pylint: disable=E0632
        fit_params = self.fit_params if self.fit_params is not None else {}

        train, _ = self.split(fold, X, y, groups)
        estimator.fit(X[train], y[train], **fit_params)
        pred = estimator.predict_proba(X)
        sklearn.externals.joblib.dump(pred, str(self.model_dir.joinpath('predict.fold{}.train.pkl'.format(fold))))
        sklearn.externals.joblib.dump(estimator, str(self.model_dir.joinpath('model.fold{}.pkl'.format(fold))))

    def oopf(self, X, y, groups=None):
        """out-of-folds predictionを作って返す。

        Xはデータの順序が変わってないかのチェック用。
        """
        self._init_data()
        oopf = sklearn.externals.joblib.load(str(self.model_dir.joinpath('predict.fold{}.train.pkl'.format(0))))
        for fold in range(1, self.cv):
            pred = sklearn.externals.joblib.load(str(self.model_dir.joinpath('predict.fold{}.train.pkl'.format(fold))))
            _, test = self.split(fold, X, y, groups)
            oopf[test] = pred[test]
        return oopf

    def _init_data(self):
        """self.data_の初期化。今のところ(?)split_seedのみ。"""
        model_json_file = self.model_dir.joinpath('model.json')
        if model_json_file.is_file():
            # あれば読み込み
            with model_json_file.open() as f:
                self.data_ = json.load(f)
        else:
            # 無ければ生成して保存
            self.data_ = {
                'split_seed': int(np.random.randint(0, 2 ** 31)),
            }
            with model_json_file.open('w') as f:
                json.dump(self.data_, f, indent=4, sort_keys=True)
