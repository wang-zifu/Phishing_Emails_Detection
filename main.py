import pandas as pd
import os

from catboost import CatBoostClassifier
from sklearn.ensemble import AdaBoostClassifier, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.naive_bayes import MultinomialNB

from sklearn.feature_selection import chi2
from sklearn.feature_selection import SelectKBest

import warnings

from Constants import RAW_DIR, LABEL_COL
from data import get_data
from features import tokenize_2
from models import StackedModel, fit_catboost

warnings.filterwarnings('ignore')


def get_validation(train_df):
    last_year = train_df['year'].max()
    train_df_before = train_df[train_df['year'] < last_year]
    train_after, validation = train_test_split(train_df[train_df['year'] == last_year], test_size=0.2)
    return pd.concat([train_df_before, train_after]), validation


def make_prediction(train_df, test_X, model_packs, feature_extractors, start_year=2017, end_year=2019,
                    debug=True, apply_chi2=True):
    if debug:
        train_df = train_df.sample(5000)
    train_df_filter = train_df[(train_df['year'] >= start_year) & (train_df['year'] <= end_year)]
    train_df_filter, validation_df_filter = get_validation(train_df_filter)
    train_X, train_y = train_df_filter['description'], train_df_filter[LABEL_COL]
    validation_X, validation_y = validation_df_filter['description'], validation_df_filter[LABEL_COL]

    for fe_name, fe_params in feature_extractors.items():
        fe = fe_params['class'](**fe_params['args'])
        fe.fit(train_X)

        train_X_fe = fe.transform(train_X)
        validation_X_fe = fe.transform(validation_X)
        test_X_fe = fe.transform(test_X['description'])
        if isinstance(fe, TfidfVectorizer):
            train_X_fe = pd.DataFrame(train_X_fe.toarray(), columns=fe.get_feature_names(), index=train_X.index)
            validation_X_fe = pd.DataFrame(validation_X_fe.toarray(), columns=fe.get_feature_names(),
                                           index=validation_X.index)
            test_X_fe = pd.DataFrame(test_X_fe.toarray(), columns=fe.get_feature_names(), index=test_X.index)

        if apply_chi2:
            fs = SelectKBest(chi2, k=300)
            train_X_fe = fs.fit_transform(train_X_fe, train_y)
            validation_X_fe = fs.transform(validation_X_fe)
            test_X_fe = fs.transform(test_X_fe)

            train_X_fe = pd.DataFrame(train_X_fe, index=train_X.index)
            validation_X_fe = pd.DataFrame(validation_X_fe, index=validation_X.index)
            test_X_fe = pd.DataFrame(test_X_fe, index=test_X.index)

        stacked_model = StackedModel()
        for model_name, model_pack in model_packs.items():
            model = model_pack["class"](**model_pack["args"])
            if isinstance(model, CatBoostClassifier):
                print("eval catboost")
                res = model.grid_search(model_pack["hyper"], X=pd.concat([train_X_fe, validation_X_fe]),
                                        y=pd.concat([train_y, validation_y]))
                best_params = res['params']
                best_params['n_estimators'] = 5000
                model = model_pack["class"](**best_params)
                clf = fit_catboost(model, train_X_fe, train_y, validation_X_fe, validation_y)
                best_score = f1_score(model.predict(validation_X_fe), validation_y, average="weighted")
            else:
                clf = GridSearchCV(model, model_pack["hyper"], scoring='f1_weighted', cv=3)
                clf.fit(pd.concat([train_X_fe, validation_X_fe]), pd.concat([train_y, validation_y]))
                best_params = clf.best_params_
                best_score = clf.best_score_
                if model_name == 'AdaBoostClassifier':
                    best_params['n_estimators'] = 1000
                elif model_name == 'RandomForestClassifier':
                    best_params['n_estimators'] = 100
                clf.fit(train_X_fe, train_y)

            stacked_model.fit_estimator(train_X_fe, train_y, model_name, model_pack["class"], best_params,
                                        validation_X_fe, validation_y
                                        )
            preds = clf.predict(test_X_fe)
            test_X[LABEL_COL] = preds
            test_X.reset_index()[['index', LABEL_COL]].to_csv(
                os.path.join(RAW_DIR, f"{int(100 * best_score)}_{model_name}_{fe_name}_submission.csv"), index=False)
        stacked_model.fit_stacked(validation_X_fe, validation_y)
        preds = stacked_model.predict(test_X_fe)
        test_X[LABEL_COL] = preds
        test_X.reset_index()[['index', LABEL_COL]].to_csv(os.path.join(RAW_DIR, f"stacked_{fe_name}_submission.csv"),
                                                          index=False)

if __name__ == "__main__":
    model_packs_ensemble = {
        "MultinomialNB": {"class": MultinomialNB, "args": {}, "hyper": {"alpha": [0.1, 0.25, 0.5, 0.75, 1.0]}},
        "AdaBoostClassifier": {"class": AdaBoostClassifier,
                               "args": {"n_estimators": 20, "random_state": 0},
                               "hyper": {"learning_rate": [0.1, 0.25, 0.5, 0.75, 1.0]}},
        "RandomForestClassifier": {"class": RandomForestClassifier,
                                   "args": {"n_estimators": 20, "random_state": 0, "n_jobs": -1},
                                   "hyper": {"criterion": ["gini", "entropy"],
                                             "max_features": ["sqrt", "log2"],
                                             "max_samples": [None, 0.5]
                                             }},
        "CatBoostClassifier": {"class": CatBoostClassifier, "args": {"n_estimators": 50, "random_state": 0}, "hyper": {
            "depth": [6, 8], "l2_leaf_reg": [1.0, 0.2, 3.0, 4.0]
        }
                               }
    }

    feature_extractors = {
        "tfidf": {
            "class": TfidfVectorizer,
            "args": {"stop_words": "english", "lowercase": True,
                     'max_df': 0.05, 'min_df': 10, 'tokenizer': tokenize_2, 'ngram_range': (1, 2)
                     }
        }
    }

    train_X, train_y, test_X = get_data(raw_dir=RAW_DIR)
    train_df = pd.concat([train_X, train_y], axis=1)

    output = make_prediction(train_df, test_X, model_packs_ensemble, feature_extractors, start_year=2017, end_year=2019,debug=True)